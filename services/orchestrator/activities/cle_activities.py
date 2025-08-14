from temporalio import activity
import httpx
import os
from typing import Dict, List, Any

@activity.defn
async def match_payment_to_invoices(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Match payment to invoices using CLE service's advanced algorithms
    """
    transaction = data.get("transaction", {})
    invoices = data.get("invoices", [])
    invoice_ids = data.get("invoice_ids", [])
    
    activity.logger.info(f"Matching payment {transaction.get('id')} to {len(invoices)} invoices")
    
    cle_base_url = os.getenv('CLE_BASE_URL', 'http://cle:8001')
    
    async with httpx.AsyncClient(timeout=45.0) as client:
        try:
            matching_payload = {
                "transaction": {
                    "id": transaction.get("id"),
                    "amount": transaction.get("amount"),
                    "reference": transaction.get("reference"),
                    "client_id": transaction.get("client_id"),
                    "payment_date": transaction.get("payment_date"),
                    "currency": transaction.get("currency", "USD")
                },
                "invoices": invoices,
                "matching_options": {
                    "tolerance": 0.01,  # Allow 1 cent tolerance
                    "partial_matching": True,
                    "multi_invoice_matching": True,
                    "use_ml_matching": True
                }
            }
            
            response = await client.post(
                f"{cle_base_url}/api/v1/match/payment-to-invoices",
                json=matching_payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                matching_result = response.json()
                
                activity.logger.info(f"Matching completed: {matching_result.get('status')} - Confidence: {matching_result.get('confidence', 0)}")
                
                # Send heartbeat with matching results
                matched_count = len(matching_result.get("matched_invoices", []))
                activity.heartbeat(f"Matched {matched_count} invoices with {matching_result.get('confidence', 0)}% confidence")
                
                return matching_result
            
            else:
                activity.logger.error(f"CLE matching service returned status {response.status_code}: {response.text}")
                raise Exception(f"CLE matching service failed with status {response.status_code}")
                
        except httpx.TimeoutException:
            activity.logger.error("CLE matching service request timed out")
            raise Exception("CLE matching service timeout")
        
        except Exception as e:
            activity.logger.error(f"Error calling CLE matching service: {str(e)}")
            raise


@activity.defn
async def validate_matching_rules(transaction_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate business rules for cash application matching
    """
    activity.logger.info(f"Validating matching rules for transaction: {transaction_data.get('transaction_id')}")
    
    cle_base_url = os.getenv('CLE_BASE_URL', 'http://cle:8001')
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{cle_base_url}/api/v1/validate/matching-rules",
                json=transaction_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                validation_result = response.json()
                
                activity.logger.info(f"Rule validation: {validation_result.get('status')} - {len(validation_result.get('violations', []))} violations")
                return validation_result
            
            else:
                activity.logger.error(f"Rule validation failed: {response.status_code}")
                raise Exception(f"Rule validation failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error validating matching rules: {str(e)}")
            raise


@activity.defn
async def calculate_matching_confidence(matching_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Calculate confidence score for payment matching using ML models
    """
    activity.logger.info(f"Calculating matching confidence for transaction: {matching_data.get('transaction_id')}")
    
    cle_base_url = os.getenv('CLE_BASE_URL', 'http://cle:8001')
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{cle_base_url}/api/v1/ml/calculate-confidence",
                json=matching_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                confidence_result = response.json()
                
                activity.logger.info(f"Confidence calculated: {confidence_result.get('confidence_score')}%")
                return confidence_result
            
            else:
                activity.logger.error(f"Confidence calculation failed: {response.status_code}")
                raise Exception(f"Confidence calculation failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error calculating matching confidence: {str(e)}")
            raise


@activity.defn
async def process_exception_handling(exception_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process exceptions and route for appropriate handling
    """
    activity.logger.info(f"Processing exception: {exception_data.get('exception_type')}")
    
    cle_base_url = os.getenv('CLE_BASE_URL', 'http://cle:8001')
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{cle_base_url}/api/v1/exceptions/process",
                json=exception_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                exception_result = response.json()
                
                activity.logger.info(f"Exception processed: {exception_result.get('resolution_action')}")
                return exception_result
            
            else:
                activity.logger.error(f"Exception processing failed: {response.status_code}")
                raise Exception(f"Exception processing failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error processing exception: {str(e)}")
            raise


@activity.defn
async def optimize_matching_parameters(optimization_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Optimize matching parameters using machine learning
    """
    activity.logger.info(f"Optimizing matching parameters for client: {optimization_data.get('client_id')}")
    
    cle_base_url = os.getenv('CLE_BASE_URL', 'http://cle:8001')
    
    async with httpx.AsyncClient(timeout=120.0) as client:  # Longer timeout for ML operations
        try:
            response = await client.post(
                f"{cle_base_url}/api/v1/ml/optimize-parameters",
                json=optimization_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                optimization_result = response.json()
                
                # Send heartbeat for long-running ML operations
                activity.heartbeat(f"Parameter optimization: {optimization_result.get('progress', 0)}% complete")
                
                activity.logger.info(f"Parameter optimization completed: {optimization_result.get('improvement')}% improvement")
                return optimization_result
            
            else:
                activity.logger.error(f"Parameter optimization failed: {response.status_code}")
                raise Exception(f"Parameter optimization failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error optimizing matching parameters: {str(e)}")
            raise


@activity.defn
async def generate_matching_report(report_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate detailed matching performance report
    """
    activity.logger.info(f"Generating matching report for period: {report_data.get('period')}")
    
    cle_base_url = os.getenv('CLE_BASE_URL', 'http://cle:8001')
    
    async with httpx.AsyncClient(timeout=90.0) as client:
        try:
            response = await client.post(
                f"{cle_base_url}/api/v1/reports/matching-performance",
                json=report_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                report_result = response.json()
                
                activity.logger.info(f"Report generated: {report_result.get('total_transactions')} transactions analyzed")
                return report_result
            
            else:
                activity.logger.error(f"Report generation failed: {response.status_code}")
                raise Exception(f"Report generation failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error generating matching report: {str(e)}")
            raise


@activity.defn
async def train_matching_model(training_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Train or retrain the matching ML model with new data
    """
    activity.logger.info(f"Starting model training with {training_data.get('sample_count', 0)} samples")
    
    cle_base_url = os.getenv('CLE_BASE_URL', 'http://cle:8001')
    
    async with httpx.AsyncClient(timeout=600.0) as client:  # 10 minute timeout for training
        try:
            response = await client.post(
                f"{cle_base_url}/api/v1/ml/train-model",
                json=training_data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {os.getenv('SERVICE_TOKEN', '')}"
                }
            )
            
            if response.status_code == 200:
                training_result = response.json()
                
                # Send periodic heartbeats during training
                activity.heartbeat(f"Model training: {training_result.get('epoch', 0)}/{training_result.get('total_epochs', 100)} epochs")
                
                activity.logger.info(f"Model training completed: {training_result.get('accuracy')}% accuracy")
                return training_result
            
            else:
                activity.logger.error(f"Model training failed: {response.status_code}")
                raise Exception(f"Model training failed with status {response.status_code}")
                
        except Exception as e:
            activity.logger.error(f"Error training matching model: {str(e)}")
            raise