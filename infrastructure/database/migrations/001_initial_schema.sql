-- database/migrations/001_initial_schema.sql
-- CashAppAgent Database Schema
-- Complete schema for autonomous financial processing
-- Supports immutable audit trails and high-performance queries

-- =============================================================================
-- EXTENSIONS AND BASIC SETUP
-- =============================================================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "btree_gin";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Create custom types
CREATE TYPE transaction_status AS ENUM (
    'pending',
    'processing', 
    'matched',
    'partially_matched',
    'unmatched',
    'requires_review',
    'error'
);

CREATE TYPE invoice_status AS ENUM (
    'open',
    'closed',
    'disputed', 
    'overdue'
);

CREATE TYPE discrepancy_code AS ENUM (
    'short_payment',
    'over_payment',
    'invalid_invoice',
    'currency_mismatch',
    'duplicate_payment'
);

CREATE TYPE communication_type AS ENUM (
    'email',
    'slack',
    'teams',
    'webhook'
);

-- =============================================================================
-- CORE BUSINESS TABLES
-- =============================================================================

-- Payment transactions from bank feeds
CREATE TABLE payment_transactions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id VARCHAR(255) UNIQUE NOT NULL,
    source_account_ref VARCHAR(255) NOT NULL,
    amount DECIMAL(15,2) NOT NULL CHECK (amount > 0),
    currency CHAR(3) NOT NULL,
    value_date TIMESTAMPTZ NOT NULL,
    raw_remittance_data TEXT,
    customer_identifier VARCHAR(255),
    processing_status transaction_status NOT NULL DEFAULT 'pending',
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    
    -- Search optimization
    remittance_search_vector TSVECTOR,
    
    -- Constraints
    CONSTRAINT valid_currency_code CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT valid_amount_precision CHECK (scale(amount) <= 2)
);

-- Invoices from ERP systems
CREATE TABLE invoices (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id VARCHAR(255) NOT NULL,
    customer_id VARCHAR(255) NOT NULL,
    customer_name VARCHAR(500),
    amount_due DECIMAL(15,2) NOT NULL CHECK (amount_due >= 0),
    original_amount DECIMAL(15,2) NOT NULL CHECK (original_amount > 0),
    currency CHAR(3) NOT NULL,
    status invoice_status NOT NULL DEFAULT 'open',
    due_date TIMESTAMPTZ,
    created_date TIMESTAMPTZ NOT NULL,
    
    -- ERP system reference
    erp_system VARCHAR(50) NOT NULL,
    erp_record_id VARCHAR(255),
    
    -- Timestamps
    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_currency_code CHECK (currency ~ '^[A-Z]{3}$'),
    CONSTRAINT valid_amount_precision CHECK (scale(amount_due) <= 2 AND scale(original_amount) <= 2),
    CONSTRAINT amount_due_not_greater_than_original CHECK (amount_due <= original_amount),
    
    -- Unique constraint per ERP system
    UNIQUE(invoice_id, erp_system)
);

-- Document references and URIs
CREATE TABLE transaction_documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id UUID NOT NULL REFERENCES payment_transactions(id) ON DELETE CASCADE,
    document_uri VARCHAR(1000) NOT NULL,
    document_type VARCHAR(50) NOT NULL, -- 'pdf', 'email', 'image'
    content_hash VARCHAR(64), -- SHA-256 hash for integrity
    file_size_bytes INTEGER,
    
    -- Processing status
    parsed BOOLEAN NOT NULL DEFAULT FALSE,
    parsing_confidence DECIMAL(3,2),
    parsing_error TEXT,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    parsed_at TIMESTAMPTZ
);

-- Payment matching results (core business logic output)
CREATE TABLE match_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id UUID NOT NULL REFERENCES payment_transactions(id) ON DELETE CASCADE,
    status transaction_status NOT NULL,
    unapplied_amount DECIMAL(15,2) NOT NULL DEFAULT 0 CHECK (unapplied_amount >= 0),
    discrepancy_code discrepancy_code,
    log_entry TEXT NOT NULL,
    confidence_score DECIMAL(3,2) CHECK (confidence_score >= 0 AND confidence_score <= 1),
    processing_time_ms INTEGER CHECK (processing_time_ms >= 0),
    requires_human_review BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Algorithm version for tracking
    algorithm_version VARCHAR(20) NOT NULL DEFAULT '1.0.0',
    
    -- Timestamps  
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_unapplied_precision CHECK (scale(unapplied_amount) <= 2)
);

-- Individual invoice-payment matches
CREATE TABLE invoice_payment_matches (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    match_result_id UUID NOT NULL REFERENCES match_results(id) ON DELETE CASCADE,
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    amount_applied DECIMAL(15,2) NOT NULL CHECK (amount_applied > 0),
    
    -- Reference to external invoice ID for audit
    external_invoice_id VARCHAR(255) NOT NULL,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_applied_precision CHECK (scale(amount_applied) <= 2),
    
    -- Prevent duplicate matches
    UNIQUE(match_result_id, invoice_id)
);

-- =============================================================================
-- ERP INTEGRATION TABLES
-- =============================================================================

-- ERP system configurations
CREATE TABLE erp_systems (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    system_name VARCHAR(50) UNIQUE NOT NULL, -- 'netsuite', 'sap', etc.
    system_version VARCHAR(20),
    base_url VARCHAR(500),
    
    -- Authentication config (encrypted)
    auth_type VARCHAR(20) NOT NULL, -- 'oauth2', 'api_key', 'certificate'
    auth_config_encrypted BYTEA, -- Encrypted JSON config
    
    -- Status
    active BOOLEAN NOT NULL DEFAULT TRUE,
    last_sync_at TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ERP operation audit trail
CREATE TABLE erp_operations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id UUID REFERENCES payment_transactions(id),
    erp_system_id UUID NOT NULL REFERENCES erp_systems(id),
    operation_type VARCHAR(50) NOT NULL, -- 'get_invoices', 'post_application', etc.
    
    -- Operation details
    request_payload JSONB,
    response_payload JSONB,
    success BOOLEAN NOT NULL,
    error_message TEXT,
    
    -- ERP transaction reference
    erp_transaction_id VARCHAR(255),
    
    -- Performance metrics
    duration_ms INTEGER NOT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- DOCUMENT INTELLIGENCE TABLES  
-- =============================================================================

-- Document parsing results
CREATE TABLE document_parsing_results (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES transaction_documents(id) ON DELETE CASCADE,
    
    -- Extracted data
    extracted_invoice_ids TEXT[], -- Array of invoice IDs found
    extracted_amounts DECIMAL(15,2)[], -- Array of amounts found
    extracted_customer_refs TEXT[], -- Array of customer identifiers
    confidence_score DECIMAL(3,2) NOT NULL CHECK (confidence_score >= 0 AND confidence_score <= 1),
    
    -- OCR and processing details
    ocr_text TEXT,
    layout_analysis JSONB, -- LayoutLMv3 output
    extraction_model VARCHAR(100) NOT NULL, -- Model used for extraction
    processing_time_ms INTEGER NOT NULL CHECK (processing_time_ms >= 0),
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- COMMUNICATION TRACKING
-- =============================================================================

-- Communication attempts and results
CREATE TABLE communication_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id UUID REFERENCES payment_transactions(id),
    
    -- Communication details
    communication_type communication_type NOT NULL,
    recipient VARCHAR(500) NOT NULL,
    template_name VARCHAR(100) NOT NULL,
    template_data JSONB,
    
    -- Delivery tracking
    sent BOOLEAN NOT NULL DEFAULT FALSE,
    delivered BOOLEAN NOT NULL DEFAULT FALSE,
    delivery_confirmation_id VARCHAR(255),
    error_message TEXT,
    
    -- Priority and scheduling
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    scheduled_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- SYSTEM MONITORING AND AUDIT
-- =============================================================================

-- Immutable system audit log
CREATE TABLE system_audit_log (
    id BIGSERIAL PRIMARY KEY, -- Use BIGSERIAL for high-volume logging
    
    -- Event details
    event_type VARCHAR(50) NOT NULL,
    event_source VARCHAR(50) NOT NULL, -- Service name
    correlation_id UUID NOT NULL,
    
    -- Event data
    event_data JSONB NOT NULL,
    user_id VARCHAR(255),
    transaction_id UUID,
    
    -- Immutable timestamp
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
) PARTITION BY RANGE (event_timestamp);

-- Create partitions for audit log (monthly partitions)
CREATE TABLE system_audit_log_202501 PARTITION OF system_audit_log
    FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
CREATE TABLE system_audit_log_202502 PARTITION OF system_audit_log
    FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
CREATE TABLE system_audit_log_202503 PARTITION OF system_audit_log
    FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');

-- System metrics snapshots
CREATE TABLE system_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    service_name VARCHAR(50) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(15,4) NOT NULL,
    metric_labels JSONB,
    
    -- Timestamp (rounded to nearest minute for aggregation)
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT date_trunc('minute', NOW()),
    
    -- Unique constraint to prevent duplicate metrics
    UNIQUE(service_name, metric_name, metric_labels, recorded_at)
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

-- Payment transactions indexes
CREATE INDEX idx_payment_transactions_status ON payment_transactions(processing_status);
CREATE INDEX idx_payment_transactions_value_date ON payment_transactions(value_date DESC);
CREATE INDEX idx_payment_transactions_customer ON payment_transactions(customer_identifier) WHERE customer_identifier IS NOT NULL;
CREATE INDEX idx_payment_transactions_currency ON payment_transactions(currency);
CREATE INDEX idx_payment_transactions_amount ON payment_transactions(amount);

-- Full-text search index for remittance data
CREATE INDEX idx_payment_transactions_fts ON payment_transactions USING GIN(remittance_search_vector);

-- Invoices indexes
CREATE INDEX idx_invoices_customer ON invoices(customer_id);
CREATE INDEX idx_invoices_status ON invoices(status);
CREATE INDEX idx_invoices_due_date ON invoices(due_date) WHERE due_date IS NOT NULL;
CREATE INDEX idx_invoices_erp_system ON invoices(erp_system);
CREATE INDEX idx_invoices_amount_due ON invoices(amount_due) WHERE amount_due > 0;
CREATE UNIQUE INDEX idx_invoices_external_id ON invoices(invoice_id, erp_system);

-- Match results indexes
CREATE INDEX idx_match_results_transaction ON match_results(transaction_id);
CREATE INDEX idx_match_results_status ON match_results(status);
CREATE INDEX idx_match_results_human_review ON match_results(requires_human_review) WHERE requires_human_review = TRUE;
CREATE INDEX idx_match_results_created ON match_results(created_at DESC);

-- Invoice payment matches indexes
CREATE INDEX idx_invoice_matches_result ON invoice_payment_matches(match_result_id);
CREATE INDEX idx_invoice_matches_invoice ON invoice_payment_matches(invoice_id);
CREATE INDEX idx_invoice_matches_amount ON invoice_payment_matches(amount_applied);

-- Document processing indexes
CREATE INDEX idx_transaction_documents_transaction ON transaction_documents(transaction_id);
CREATE INDEX idx_transaction_documents_type ON transaction_documents(document_type);
CREATE INDEX idx_transaction_documents_parsed ON transaction_documents(parsed);

-- ERP operations indexes
CREATE INDEX idx_erp_operations_transaction ON erp_operations(transaction_id);
CREATE INDEX idx_erp_operations_system ON erp_operations(erp_system_id);
CREATE INDEX idx_erp_operations_success ON erp_operations(success);
CREATE INDEX idx_erp_operations_created ON erp_operations(created_at DESC);

-- Communication log indexes  
CREATE INDEX idx_communication_log_transaction ON communication_log(transaction_id);
CREATE INDEX idx_communication_log_sent ON communication_log(sent);
CREATE INDEX idx_communication_log_type ON communication_log(communication_type);

-- Audit log indexes
CREATE INDEX idx_audit_log_event_type ON system_audit_log(event_type);
CREATE INDEX idx_audit_log_correlation ON system_audit_log(correlation_id);
CREATE INDEX idx_audit_log_transaction ON system_audit_log(transaction_id) WHERE transaction_id IS NOT NULL;
CREATE INDEX idx_audit_log_timestamp ON system_audit_log(event_timestamp DESC);

-- System metrics indexes
CREATE INDEX idx_system_metrics_service ON system_metrics(service_name, recorded_at DESC);
CREATE INDEX idx_system_metrics_recorded ON system_metrics(recorded_at DESC);

-- =============================================================================
-- FUNCTIONS AND TRIGGERS
-- =============================================================================

-- Function to update timestamps
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Function to update remittance search vector
CREATE OR REPLACE FUNCTION update_remittance_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.raw_remittance_data IS NOT NULL THEN
        NEW.remittance_search_vector := to_tsvector('english', NEW.raw_remittance_data);
    END IF;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for updated_at
CREATE TRIGGER update_payment_transactions_updated_at
    BEFORE UPDATE ON payment_transactions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_invoices_updated_at
    BEFORE UPDATE ON invoices
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_erp_systems_updated_at
    BEFORE UPDATE ON erp_systems
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger for search vector updates
CREATE TRIGGER update_payment_transactions_search_vector
    BEFORE INSERT OR UPDATE ON payment_transactions
    FOR EACH ROW
    EXECUTE FUNCTION update_remittance_search_vector();

-- =============================================================================
-- VIEWS FOR REPORTING AND MONITORING
-- =============================================================================

-- Business metrics view
CREATE VIEW business_metrics_daily AS
SELECT 
    DATE(created_at) as business_date,
    processing_status,
    discrepancy_code,
    COUNT(*) as transaction_count,
    SUM(amount) as total_amount,
    currency,
    AVG(processing_time_ms) as avg_processing_time_ms,
    COUNT(*) FILTER (WHERE requires_human_review) as requires_review_count
FROM payment_transactions pt
LEFT JOIN match_results mr ON pt.id = mr.transaction_id  
WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY DATE(created_at), processing_status, discrepancy_code, currency;

-- System performance view
CREATE VIEW system_performance_hourly AS
SELECT 
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as transactions_processed,
    AVG(processing_time_ms) as avg_processing_time_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY processing_time_ms) as p95_processing_time_ms,
    COUNT(*) FILTER (WHERE status = 'matched') as successful_matches,
    COUNT(*) FILTER (WHERE requires_human_review) as human_review_required
FROM match_results
WHERE created_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
GROUP BY DATE_TRUNC('hour', created_at)
ORDER BY hour DESC;

-- Audit trail view for compliance
CREATE VIEW audit_trail AS
SELECT 
    pt.transaction_id,
    pt.amount,
    pt.currency,
    pt.created_at as transaction_received,
    mr.created_at as processed_at,
    mr.status as final_status,
    mr.log_entry as processing_summary,
    COALESCE(
        JSON_AGG(
            JSON_BUILD_OBJECT(
                'invoice_id', ipm.external_invoice_id,
                'amount_applied', ipm.amount_applied
            )
        ) FILTER (WHERE ipm.id IS NOT NULL), 
        '[]'::json
    ) as invoice_applications,
    cl.sent as communication_sent,
    cl.template_name as communication_template
FROM payment_transactions pt
LEFT JOIN match_results mr ON pt.id = mr.transaction_id
LEFT JOIN invoice_payment_matches ipm ON mr.id = ipm.match_result_id
LEFT JOIN communication_log cl ON pt.id = cl.transaction_id
WHERE pt.created_at >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY pt.id, pt.transaction_id, pt.amount, pt.currency, pt.created_at,
         mr.created_at, mr.status, mr.log_entry, cl.sent, cl.template_name
ORDER BY pt.created_at DESC;

-- =============================================================================
-- SECURITY AND PERMISSIONS
-- =============================================================================

-- Create application roles
CREATE ROLE cashapp_reader;
CREATE ROLE cashapp_writer; 
CREATE ROLE cashapp_admin;

-- Grant permissions to reader role
GRANT SELECT ON ALL TABLES IN SCHEMA public TO cashapp_reader;
GRANT USAGE ON SCHEMA public TO cashapp_reader;

-- Grant permissions to writer role (includes reader)
GRANT cashapp_reader TO cashapp_writer;
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cashapp_writer;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cashapp_writer;

-- Grant all permissions to admin role
GRANT cashapp_writer TO cashapp_admin;
GRANT ALL PRIVILEGES ON SCHEMA public TO cashapp_admin;
GRANT CREATE ON SCHEMA public TO cashapp_admin;

-- =============================================================================
-- INITIAL CONFIGURATION DATA
-- =============================================================================

-- Insert system configuration
INSERT INTO erp_systems (system_name, system_version, auth_type, active) VALUES
('netsuite', '2024.1', 'oauth2', true),
('sap', 'S/4HANA 2023', 'certificate', true),
('quickbooks', '2024', 'oauth2', false);

-- =============================================================================
-- COMMENTS FOR DOCUMENTATION  
-- =============================================================================

COMMENT ON TABLE payment_transactions IS 'Core table storing all incoming payment transactions from bank feeds';
COMMENT ON TABLE invoices IS 'Invoice data synchronized from ERP systems';
COMMENT ON TABLE match_results IS 'Results of the payment matching algorithm - core business logic output';
COMMENT ON TABLE invoice_payment_matches IS 'Individual invoice-payment allocations from successful matches';
COMMENT ON TABLE system_audit_log IS 'Immutable audit trail for all system operations - partitioned by month';
COMMENT ON TABLE erp_operations IS 'Audit trail of all ERP system interactions';
COMMENT ON TABLE document_parsing_results IS 'ML model outputs from document intelligence processing';
COMMENT ON TABLE communication_log IS 'Record of all autonomous communications sent by the system';

COMMENT ON COLUMN payment_transactions.remittance_search_vector IS 'Full-text search vector for remittance advice matching';
COMMENT ON COLUMN invoices.erp_record_id IS 'Reference to the record ID in the originating ERP system';
COMMENT ON COLUMN match_results.algorithm_version IS 'Version of matching algorithm used - for A/B testing and rollback';
COMMENT ON COLUMN erp_systems.auth_config_encrypted IS 'Encrypted JSON containing OAuth tokens, certificates, etc.';

-- =============================================================================
-- PERFORMANCE OPTIMIZATION HINTS
-- =============================================================================

-- Set appropriate autovacuum settings for high-volume tables
ALTER TABLE system_audit_log SET (
    autovacuum_vacuum_scale_factor = 0.01,
    autovacuum_analyze_scale_factor = 0.005
);

ALTER TABLE system_metrics SET (
    autovacuum_vacuum_scale_factor = 0.02,
    autovacuum_analyze_scale_factor = 0.01
);

-- Enable parallel queries for large analytical queries
SET max_parallel_workers_per_gather = 4;
SET max_parallel_workers = 8;