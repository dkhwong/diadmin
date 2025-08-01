import streamlit as st
import os
import pandas as pd
import requests
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.ai.documentintelligence import DocumentIntelligenceAdministrationClient
from azure.identity import DefaultAzureCredential, CredentialUnavailableError
from azure.keyvault.secrets import SecretClient

# Load environment variables from .env file
load_dotenv()

# --- Page Configuration ---
st.set_page_config(
    page_title="DI Model Manager",
    page_icon="📄",
    layout="wide"
)

st.title("Azure Document Intelligence Model Manager")
st.write("A tool to list and copy custom models between Document Intelligence resources.")
st.info("This tool uses `DefaultAzureCredential` to access Key Vault. For local development, please ensure you are logged in via the Azure CLI (`az login`).")
st.info("Configuration is loaded from the `.env` file.")

# --- Helper Functions ---
@st.cache_resource
def get_secret_client(key_vault_url):
    """Creates and returns a SecretClient using DefaultAzureCredential."""
    try:
        print(f"🔑 Connecting to Key Vault: {key_vault_url}")
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=key_vault_url, credential=credential)
        
        # Test the connection by trying to list secrets (this will fail if no permissions, but connection works)
        try:
            # This will test if we can authenticate to the Key Vault
            list(client.list_properties_of_secrets(max_page_size=1))
            print("✅ Successfully connected to Key Vault with DefaultAzureCredential")
        except Exception as perm_error:
            print(f"⚠️ Connected to Key Vault but may have limited permissions: {perm_error}")
            
        return client
    except CredentialUnavailableError:
        st.error("❌ Azure credential not available. Please log in via Azure CLI (`az login`).")
        return None
    except Exception as e:
        st.error(f"❌ Failed to connect to Key Vault '{key_vault_url}': {e}")
        return None

def get_api_key_from_kv(kv_client, secret_name):
    """Fetches a secret from Azure Key Vault."""
    if not kv_client or not secret_name:
        return None
    try:
        secret = kv_client.get_secret(secret_name)
        print(f"✅ Successfully retrieved secret '{secret_name}' from Key Vault")
        # Only show first few characters for security
        masked_value = secret.value[:8] + "..." if len(secret.value) > 8 else "***"
        print(f"Secret value starts with: {masked_value}")
        return secret.value
    except Exception as e:
        st.error(f"❌ Failed to retrieve secret '{secret_name}': {e}")
        return None

def test_di_connection(di_client):
    """Test the Document Intelligence client connection."""
    try:
        # Try to get resource details - this is a lightweight operation
        resource_details = di_client.get_resource_details()
        print(f"✅ Document Intelligence connection successful!")
        print(f"📊 Resource details: Custom models limit: {resource_details.custom_document_models.limit}, Used: {resource_details.custom_document_models.count}")
        return True
    except ClientAuthenticationError as auth_error:
        st.error(f"❌ Authentication failed: {auth_error}")
        st.error("🔍 This usually means the API key is incorrect or the endpoint URL is wrong.")
        return False
    except HttpResponseError as http_error:
        st.error(f"❌ HTTP Error: {http_error}")
        if "401" in str(http_error):
            st.error("🔍 401 Unauthorized - Check your API key")
        elif "403" in str(http_error):
            st.error("🔍 403 Forbidden - Check your permissions") 
        elif "404" in str(http_error):
            st.error("🔍 404 Not Found - Check your endpoint URL")
        return False
    except Exception as e:
        st.error(f"❌ Connection test failed: {e}")
        return False

def get_admin_client(endpoint, key):
    """Creates and returns a DocumentIntelligenceAdministrationClient."""
    if not endpoint or not key:
        st.error("❌ Missing endpoint or key for DI client creation")
        return None
    try:
        print(f"🔗 Creating DI client for endpoint: {endpoint}")
        client = DocumentIntelligenceAdministrationClient(endpoint=endpoint, credential=AzureKeyCredential(key))
        print("✅ Successfully created DocumentIntelligence client")
        return client
    except Exception as e:
        st.error(f"❌ Failed to create DI client for endpoint {endpoint}: {e}")
        return None

def authorize_copy_model(target_endpoint, target_key, model_id, description=""):
    """
    Authorize a model copy operation on the target endpoint.
    Returns the copy authorization object needed for the copy operation.
    """
    url = f"{target_endpoint}/formrecognizer/documentModels:authorizeCopy?api-version=2023-07-31"
    headers = {
        "Ocp-Apim-Subscription-Key": target_key,
        "Content-Type": "application/json"
    }
    body = {
        "modelId": model_id,
        "description": description
    }
    
    try:
        print(f"🔑 Authorizing copy for model '{model_id}' on target endpoint")
        response = requests.post(url, headers=headers, json=body, timeout=30)
        response.raise_for_status()
        
        auth_result = response.json()
        print(f"✅ Copy authorization successful for model '{model_id}'")
        print(f"Target Resource ID: {auth_result.get('targetResourceId', 'N/A')}")
        return auth_result
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to authorize copy for model '{model_id}': {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"Error details: {error_detail}")
                return {"error": f"HTTP {e.response.status_code}: {error_detail.get('error', {}).get('message', str(e))}"}
            except:
                return {"error": f"HTTP {e.response.status_code}: {str(e)}"}
        return {"error": str(e)}

def copy_model_to_target(source_endpoint, source_key, source_model_id, copy_authorization):
    """
    Initiate the copy operation from the source endpoint using the copy authorization.
    Returns the operation location for status tracking.
    """
    url = f"{source_endpoint}/formrecognizer/documentModels/{source_model_id}:copyTo?api-version=2023-07-31"
    headers = {
        "Ocp-Apim-Subscription-Key": source_key,
        "Content-Type": "application/json"
    }
    
    try:
        print(f"📋 Initiating copy operation for model '{source_model_id}' from source endpoint")
        response = requests.post(url, headers=headers, json=copy_authorization, timeout=30)
        response.raise_for_status()
        
        # Get the operation location from the response headers
        operation_location = response.headers.get('Operation-Location')
        if operation_location:
            print(f"✅ Copy operation initiated successfully")
            print(f"Operation Location: {operation_location}")
            return {"operation_location": operation_location, "status": "initiated"}
        else:
            print("⚠️ Copy operation response received but no Operation-Location header found")
            return {"error": "No Operation-Location header in response"}
            
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to initiate copy for model '{source_model_id}': {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                print(f"Error details: {error_detail}")
                return {"error": f"HTTP {e.response.status_code}: {error_detail.get('error', {}).get('message', str(e))}"}
            except:
                return {"error": f"HTTP {e.response.status_code}: {str(e)}"}
        return {"error": str(e)}

def check_copy_status(operation_location, api_key):
    """
    Check the status of a copy operation using the operation location URL.
    Returns the current status of the copy operation.
    """
    headers = {
        "Ocp-Apim-Subscription-Key": api_key
    }
    
    try:
        print(f"🔍 Checking copy operation status: {operation_location}")
        response = requests.get(operation_location, headers=headers, timeout=30)
        response.raise_for_status()
        
        status_result = response.json()
        status = status_result.get('status', 'unknown')
        print(f"📊 Copy operation status: {status}")
        
        if status.lower() == 'succeeded':
            print(f"✅ Copy operation completed successfully")
            if 'result' in status_result:
                print(f"Result: {status_result['result']}")
        elif status.lower() == 'failed':
            print(f"❌ Copy operation failed")
            if 'error' in status_result:
                print(f"Error: {status_result['error']}")
        elif status.lower() in ['running', 'notstarted']:
            print(f"⏳ Copy operation still in progress...")
        
        return status_result
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to check copy status: {e}")
        if hasattr(e, 'response') and e.response is not None:
            try:
                error_detail = e.response.json()
                return {"error": f"HTTP {e.response.status_code}: {error_detail.get('error', {}).get('message', str(e))}"}
            except:
                return {"error": f"HTTP {e.response.status_code}: {str(e)}"}
        return {"error": str(e)}

# --- Get configuration from environment variables ---
source_endpoint = os.getenv("SOURCE_ENDPOINT")
source_kv_url = os.getenv("SOURCE_KV_URL")
source_secret_name = os.getenv("SOURCE_SECRET_NAME")

# Target environment configurations
target1_endpoint = os.getenv("TARGET1_ENDPOINT")
target1_kv_url = os.getenv("TARGET1_KV_URL")
target1_secret_name = os.getenv("TARGET1_SECRET_NAME")
target1_name = os.getenv("TARGET1_NAME", "Target 1")

target2_endpoint = os.getenv("TARGET2_ENDPOINT")
target2_kv_url = os.getenv("TARGET2_KV_URL")
target2_secret_name = os.getenv("TARGET2_SECRET_NAME")
target2_name = os.getenv("TARGET2_NAME", "Target 2")

target3_endpoint = os.getenv("TARGET3_ENDPOINT")
target3_kv_url = os.getenv("TARGET3_KV_URL")
target3_secret_name = os.getenv("TARGET3_SECRET_NAME")
target3_name = os.getenv("TARGET3_NAME", "Target 3")

# --- Configuration Validation ---
st.subheader("🔧 Configuration Status")
config_col1, config_col2 = st.columns([1, 2])

with config_col1:
    st.write("**Source Configuration:**")
    st.write(f"✅ Endpoint: {source_endpoint}" if source_endpoint else "❌ SOURCE_ENDPOINT not set")
    st.write(f"✅ Key Vault: {source_kv_url}" if source_kv_url else "❌ SOURCE_KV_URL not set")
    st.write(f"✅ Secret Name: {source_secret_name}" if source_secret_name else "❌ SOURCE_SECRET_NAME not set")

with config_col2:
    st.write("**Target Environments Configuration:**")
    
    # Target 1
    target1_status = "✅" if all([target1_endpoint, target1_kv_url, target1_secret_name]) else "❌"
    st.write(f"{target1_status} **{target1_name}:** {target1_endpoint or 'Not configured'}")
    
    # Target 2
    target2_status = "✅" if all([target2_endpoint, target2_kv_url, target2_secret_name]) else "❌"
    st.write(f"{target2_status} **{target2_name}:** {target2_endpoint or 'Not configured'}")
    
    # Target 3
    target3_status = "✅" if all([target3_endpoint, target3_kv_url, target3_secret_name]) else "❌"
    st.write(f"{target3_status} **{target3_name}:** {target3_endpoint or 'Not configured'}")

# Create target configurations list for easier handling
target_configs = [
    {
        "name": target1_name,
        "endpoint": target1_endpoint,
        "kv_url": target1_kv_url,
        "secret_name": target1_secret_name,
        "key": "target1"
    },
    {
        "name": target2_name,
        "endpoint": target2_endpoint,
        "kv_url": target2_kv_url,
        "secret_name": target2_secret_name,
        "key": "target2"
    },
    {
        "name": target3_name,
        "endpoint": target3_endpoint,
        "kv_url": target3_kv_url,
        "secret_name": target3_secret_name,
        "key": "target3"
    }
]

# Filter out unconfigured targets
configured_targets = [config for config in target_configs if all([config["endpoint"], config["kv_url"], config["secret_name"]])]

if not configured_targets:
    st.warning("⚠️ No target environments are properly configured. Please check your .env file.")
    st.info("Expected environment variables: TARGET1_ENDPOINT, TARGET1_KV_URL, TARGET1_SECRET_NAME, etc.")

st.markdown("---")


# --- Session State Initialization ---
if 'models_list' not in st.session_state:
    st.session_state.models_list = []
if 'target_models_lists' not in st.session_state:
    st.session_state.target_models_lists = {}
    # Initialize target model lists for each configured target
    for target_config in configured_targets:
        st.session_state.target_models_lists[target_config["key"]] = []

# --- UI Layout ---
col1, col2 = st.columns(2)

# --- Source Column ---
with col1:
    st.header("Source Resource")
    st.write(f"**Endpoint:** `{source_endpoint}`")
    st.write(f"**Key Vault:** `{source_kv_url}`")


    if st.button("Get Models from Source", use_container_width=True):
        if not all([source_endpoint, source_kv_url, source_secret_name]):
            st.warning("Please ensure SOURCE_ENDPOINT, SOURCE_KV_URL, and SOURCE_SECRET_NAME are set in your .env file.")
        else:
            kv_client = get_secret_client(source_kv_url)
            if kv_client:
                with st.spinner("Fetching API key from Key Vault..."):
                    source_key = get_api_key_from_kv(kv_client, source_secret_name)
                
                if source_key:
                    di_client = get_admin_client(source_endpoint, source_key)
                    if di_client:
                        # Test the connection first
                        if test_di_connection(di_client):
                            with st.spinner("Fetching models..."):
                                try:
                                    models = di_client.list_models()
                                    # Filter to only include custom models (exclude prebuilt models)
                                    custom_models = [m for m in models if hasattr(m, 'model_id') and not m.model_id.startswith('prebuilt-')]
                                    st.session_state.models_list = custom_models
                                    if st.session_state.models_list:
                                        st.success(f"✅ Found {len(st.session_state.models_list)} custom models")
                                        print(f"Source models fetched: {[m.model_id for m in st.session_state.models_list]}")
                                        # Show model details in an expandable section
                                        with st.expander("📋 Custom Model Details"):
                                            for model in st.session_state.models_list:
                                                st.write(f"• **{model.model_id}** - Created: {model.created_date_time.strftime('%Y-%m-%d %H:%M') if hasattr(model, 'created_date_time') and model.created_date_time else 'Unknown'}")
                                    else:
                                        st.info("No custom models found on the source resource.")
                                except Exception as e:
                                    st.error(f"An error occurred while fetching models: {e}")
                        else:
                            st.error("Cannot proceed with model listing due to connection issues.")

# --- Target Environments Section ---
with col2:
    st.header("Target Environments")
    
    if not configured_targets:
        st.warning("No target environments configured. Please check your .env file.")
        st.info("Expected format: TARGET1_ENDPOINT, TARGET1_KV_URL, TARGET1_SECRET_NAME, etc.")
    else:
        # Create tabs for each target environment
        target_tabs = st.tabs([config["name"] for config in configured_targets])
        
        for i, (tab, target_config) in enumerate(zip(target_tabs, configured_targets)):
            with tab:
                st.write(f"**Endpoint:** `{target_config['endpoint']}`")
                st.write(f"**Key Vault:** `{target_config['kv_url']}`")
                
                # Button to check target models
                if st.button(f"Check {target_config['name']} Models", key=f"check_{target_config['key']}", use_container_width=True):
                    kv_client = get_secret_client(target_config['kv_url'])
                    if kv_client:
                        with st.spinner("Fetching API key from Key Vault..."):
                            target_key = get_api_key_from_kv(kv_client, target_config['secret_name'])
                        
                        if target_key:
                            di_client = get_admin_client(target_config['endpoint'], target_key)
                            if di_client:
                                # Test the connection first
                                if test_di_connection(di_client):
                                    with st.spinner(f"Fetching {target_config['name']} models..."):
                                        try:
                                            models = di_client.list_models()
                                            # Filter to only include custom models (exclude prebuilt models)
                                            custom_models = [m for m in models if hasattr(m, 'model_id') and not m.model_id.startswith('prebuilt-')]
                                            st.session_state.target_models_lists[target_config['key']] = custom_models
                                            if custom_models:
                                                st.success(f"✅ Found {len(custom_models)} custom models in {target_config['name']}")
                                                print(f"{target_config['name']} models fetched: {[m.model_id for m in custom_models]}")
                                                # Show model details in an expandable section
                                                with st.expander(f"📋 {target_config['name']} Custom Model Details"):
                                                    for model in custom_models:
                                                        st.write(f"• **{model.model_id}** - Created: {model.created_date_time.strftime('%Y-%m-%d %H:%M') if hasattr(model, 'created_date_time') and model.created_date_time else 'Unknown'}")
                                            else:
                                                st.info(f"No custom models found on {target_config['name']}.")
                                        except Exception as e:
                                            st.error(f"An error occurred while fetching {target_config['name']} models: {e}")
                                else:
                                    st.error(f"Cannot proceed with model listing due to connection issues with {target_config['name']}.")
    
    st.markdown("---")

# --- Model Selection and Copy Section ---
st.header("🔄 Model Copy Operations")

if not st.session_state.models_list:
    st.info("Fetch models from a source resource to see copy options.")
elif not configured_targets:
    st.warning("No target environments configured. Please check your .env file.")
else:
    # Get all target model IDs to filter out existing models
    all_target_model_ids = set()
    for target_key in st.session_state.target_models_lists:
        target_models = st.session_state.target_models_lists[target_key]
        all_target_model_ids.update(model.model_id for model in target_models)
    
    # Filter available models (models that don't exist in any target)
    available_models = [model for model in st.session_state.models_list if model.model_id not in all_target_model_ids]
    
    if not available_models:
        st.warning("All source models already exist in at least one target environment.")
        st.info("Use the 'Check Target Models' buttons to refresh target model lists.")
    else:
        # Sort models by creation date (newest first)
        sorted_models = sorted(
            available_models,
            key=lambda m: m.created_date_time if hasattr(m, 'created_date_time') and m.created_date_time else datetime.min.replace(tzinfo=timezone.utc),
            reverse=True
        )
        
        print(f"Available models for copying: {[m.model_id for m in sorted_models]}")
        
        # Create table data for display
        import pandas as pd
        from datetime import datetime, timezone
        
        table_data = []
        model_id_to_model = {}
        
        for model in sorted_models:
            created_date = model.created_date_time.strftime('%Y-%m-%d %H:%M') if hasattr(model, 'created_date_time') and model.created_date_time else 'Unknown'
            table_data.append({
                'Select': False,
                'Model ID': model.model_id,
                'Created Date': created_date,
                'Target ID': model.model_id  # Default to same name as source
            })
            model_id_to_model[model.model_id] = model
        
        # Display table with selection
        st.write(f"**{len(available_models)} Models Available for Copying (sorted by creation date):**")
        
        # Create DataFrame for better display
        df = pd.DataFrame(table_data)
        
        # Use data_editor for interactive selection
        edited_df = st.data_editor(
            df,
            column_config={
                "Select": st.column_config.CheckboxColumn(
                    "Select",
                    help="Check to select models for copying",
                    default=False,
                ),
                "Model ID": st.column_config.TextColumn(
                    "Model ID",
                    help="Source model identifier",
                    disabled=True,
                ),
                "Created Date": st.column_config.TextColumn(
                    "Created Date",
                    help="When the model was created",
                    disabled=True,
                ),
                "Target ID": st.column_config.TextColumn(
                    "Target ID",
                    help="Target model identifier (will be updated based on suffix)",
                    disabled=True,
                ),
            },
            disabled=["Model ID", "Created Date", "Target ID"],
            hide_index=True,
            use_container_width=True,
            height=min(400, len(table_data) * 35 + 70)  # Dynamic height based on row count
        )
        
        # Get selected model IDs
        selected_model_ids = [row['Model ID'] for _, row in edited_df.iterrows() if row['Select']]
        
        # Copy configuration section
        col_suffix, col_targets = st.columns([1, 2])
        
        with col_suffix:
            # Copy suffix input
            copy_suffix = st.text_input(
                "Suffix for copied models", 
                value="",
                help="Optional suffix to append to each model ID in the target resource. Leave empty to use the same name as source."
            )
        
        with col_targets:
            # Target environment selection
            st.write("**Select target environments:**")
            selected_targets = []
            for target_config in configured_targets:
                if st.checkbox(target_config["name"], key=f"target_select_{target_config['key']}"):
                    selected_targets.append(target_config)
        
        # Update the table data when suffix changes
        if copy_suffix:
            # Recreate table data with updated target IDs
            updated_table_data = []
            for model in sorted_models:
                created_date = model.created_date_time.strftime('%Y-%m-%d %H:%M') if hasattr(model, 'created_date_time') and model.created_date_time else 'Unknown'
                # Check if this model was previously selected
                was_selected = model.model_id in selected_model_ids
                updated_table_data.append({
                    'Select': was_selected,
                    'Model ID': model.model_id,
                    'Created Date': created_date,
                    'Target ID': f"{model.model_id}{copy_suffix}"
                })
            
            # Update the DataFrame and display updated table
            st.write("**Updated table with custom suffix:**")
            updated_df = pd.DataFrame(updated_table_data)
            
            # Use data_editor for interactive selection with updated data
            edited_df = st.data_editor(
                updated_df,
                column_config={
                    "Select": st.column_config.CheckboxColumn(
                        "Select",
                        help="Check to select models for copying",
                        default=False,
                    ),
                    "Model ID": st.column_config.TextColumn(
                        "Model ID",
                        help="Source model identifier",
                        disabled=True,
                    ),
                    "Created Date": st.column_config.TextColumn(
                        "Created Date",
                        help="When the model was created",
                        disabled=True,
                    ),
                    "Target ID": st.column_config.TextColumn(
                        "Target ID",
                        help="Target model identifier with custom suffix",
                        disabled=True,
                    ),
                },
                disabled=["Model ID", "Created Date", "Target ID"],
                hide_index=True,
                use_container_width=True,
                height=min(400, len(updated_table_data) * 35 + 70),
                key="updated_table"  # Different key to force re-render
            )
            
            # Get updated selected model IDs
            selected_model_ids = [row['Model ID'] for _, row in edited_df.iterrows() if row['Select']]
        
        # Show summary of selected models and targets
        if selected_model_ids:
            st.success(f"✅ Selected {len(selected_model_ids)} models for copying")
            print(f"Selected models: {selected_model_ids}")
            
            if selected_targets:
                st.info(f"📍 Selected targets: {', '.join([t['name'] for t in selected_targets])}")
                
                with st.expander("📋 Copy Operation Summary"):
                    for model_id in selected_model_ids:
                        model = model_id_to_model[model_id]
                        created_date = model.created_date_time.strftime('%Y-%m-%d %H:%M') if hasattr(model, 'created_date_time') and model.created_date_time else 'Unknown'
                        target_name = f"{model_id}{copy_suffix}" if copy_suffix else model_id
                        st.write(f"• **{model_id}** (Created: {created_date}) → `{target_name}`")
                    
                    st.write("**Will be copied to:**")
                    for target in selected_targets:
                        st.write(f"  - {target['name']} ({target['endpoint']})")
            else:
                st.warning("Please select at least one target environment.")

        # Copy button
        copy_disabled = not selected_model_ids or not selected_targets
        if st.button(
            f"Copy {len(selected_model_ids)} Models to {len(selected_targets) if selected_targets else 0} Targets", 
            use_container_width=True, 
            type="primary", 
            disabled=copy_disabled
        ):
            if not selected_model_ids:
                st.warning("Please select at least one model to copy.")
            elif not selected_targets:
                st.warning("Please select at least one target environment.")
            else:
                # Get source key for the copy operation
                source_kv_client = get_secret_client(source_kv_url)
                source_key = get_api_key_from_kv(source_kv_client, source_secret_name) if source_kv_client else None

                if not source_key:
                    st.error("Failed to retrieve source API key.")
                else:
                    source_di_client = get_admin_client(source_endpoint, source_key)
                    if not source_di_client:
                        st.error("Failed to create source DI client.")
                    else:
                        # Start the copy operation
                        total_operations = len(selected_model_ids) * len(selected_targets)
                        with st.status(f"Copying {len(selected_model_ids)} models to {len(selected_targets)} targets ({total_operations} total operations)...", expanded=True) as status:
                            try:
                                print(f"Starting multi-target copy operation: {len(selected_model_ids)} models to {len(selected_targets)} targets")
                                st.write(f"Preparing to copy {len(selected_model_ids)} models to {len(selected_targets)} target environments...")
                                
                                all_results = {target['name']: {'successful': [], 'failed': []} for target in selected_targets}
                                operation_count = 0
                                
                                for target_config in selected_targets:
                                    st.write(f"\n🎯 **Starting copy operations to {target_config['name']}**")
                                    
                                    # Get target credentials
                                    target_kv_client = get_secret_client(target_config['kv_url'])
                                    target_key = get_api_key_from_kv(target_kv_client, target_config['secret_name']) if target_kv_client else None
                                    
                                    if not target_key:
                                        st.error(f"❌ Failed to retrieve API key for {target_config['name']}")
                                        for model_id in selected_model_ids:
                                            all_results[target_config['name']]['failed'].append({
                                                "model_id": model_id, 
                                                "error": "Failed to retrieve target API key"
                                            })
                                        continue
                                    
                                    target_di_client = get_admin_client(target_config['endpoint'], target_key)
                                    if not target_di_client:
                                        st.error(f"❌ Failed to create DI client for {target_config['name']}")
                                        for model_id in selected_model_ids:
                                            all_results[target_config['name']]['failed'].append({
                                                "model_id": model_id, 
                                                "error": "Failed to create target DI client"
                                            })
                                        continue
                                    
                                    # Copy each model to this target
                                    for model_id in selected_model_ids:
                                        operation_count += 1
                                        new_model_id = f"{model_id}{copy_suffix}" if copy_suffix else model_id
                                        
                                        st.write(f"[{operation_count}/{total_operations}] Copying '{model_id}' to '{new_model_id}' in {target_config['name']}...")
                                        
                                        # Step 1: Authorize copy on target
                                        st.write(f"  🔑 Authorizing copy...")
                                        copy_auth = authorize_copy_model(target_config['endpoint'], target_key, new_model_id, f"Copied from {source_endpoint} {model_id}")
                                        
                                        if "error" in copy_auth:
                                            st.error(f"  ❌ Authorization failed: {copy_auth['error']}")
                                            all_results[target_config['name']]['failed'].append({
                                                "model_id": model_id, 
                                                "error": f"Authorization failed: {copy_auth['error']}"
                                            })
                                            continue
                                        
                                        # Step 2: Initiate copy from source
                                        st.write(f"  📋 Initiating copy...")
                                        copy_result = copy_model_to_target(source_endpoint, source_key, model_id, copy_auth)
                                        
                                        if "error" in copy_result:
                                            st.error(f"  ❌ Copy initiation failed: {copy_result['error']}")
                                            all_results[target_config['name']]['failed'].append({
                                                "model_id": model_id, 
                                                "error": f"Copy initiation failed: {copy_result['error']}"
                                            })
                                            continue
                                        
                                        operation_location = copy_result["operation_location"]
                                        
                                        # Step 3: Monitor copy status
                                        st.write(f"  ⏳ Monitoring progress...")
                                        max_attempts = 30
                                        attempt = 0
                                        copy_completed = False
                                        
                                        while attempt < max_attempts:
                                            attempt += 1
                                            status_result = check_copy_status(operation_location, source_key)
                                            
                                            if "error" in status_result:
                                                st.error(f"  ❌ Status check failed: {status_result['error']}")
                                                all_results[target_config['name']]['failed'].append({
                                                    "model_id": model_id, 
                                                    "error": f"Status check failed: {status_result['error']}"
                                                })
                                                break
                                            
                                            status = status_result.get('status', '').lower()
                                            
                                            if status == 'succeeded':
                                                st.success(f"  ✅ Copy completed successfully!")
                                                all_results[target_config['name']]['successful'].append({
                                                    "model_id": model_id, 
                                                    "new_model_id": new_model_id
                                                })
                                                copy_completed = True
                                                break
                                            elif status == 'failed':
                                                error_info = status_result.get('error', {})
                                                if isinstance(error_info, dict):
                                                    error_msg = error_info.get('message', 'Unknown error')
                                                else:
                                                    error_msg = str(error_info)
                                                st.error(f"  ❌ Copy failed: {error_msg}")
                                                all_results[target_config['name']]['failed'].append({
                                                    "model_id": model_id, 
                                                    "error": error_msg
                                                })
                                                break
                                            elif status in ['running', 'notstarted']:
                                                if attempt % 5 == 0:
                                                    st.write(f"  ⏳ Copy in progress... (attempt {attempt}/{max_attempts})")
                                                time.sleep(2)
                                            else:
                                                st.write(f"  ❓ Unknown status: {status}")
                                                time.sleep(2)
                                        
                                        if not copy_completed and attempt >= max_attempts:
                                            st.warning(f"  ⏰ Copy operation timed out")
                                            all_results[target_config['name']]['failed'].append({
                                                "model_id": model_id, 
                                                "error": "Copy operation timed out"
                                            })
                                
                                # Display comprehensive summary
                                st.write("\n" + "="*60)
                                st.write("📊 **Multi-Target Copy Operation Summary:**")
                                
                                total_successful = sum(len(results['successful']) for results in all_results.values())
                                total_failed = sum(len(results['failed']) for results in all_results.values())
                                
                                st.write(f"**Overall Results:** {total_successful} successful, {total_failed} failed out of {total_operations} total operations")
                                
                                for target_name, results in all_results.items():
                                    st.write(f"\n🎯 **{target_name}:**")
                                    
                                    if results['successful']:
                                        st.success(f"✅ Successfully copied {len(results['successful'])} models:")
                                        for copy in results['successful']:
                                            st.write(f"  • {copy['model_id']} → {copy['new_model_id']}")
                                    
                                    if results['failed']:
                                        st.error(f"❌ Failed to copy {len(results['failed'])} models:")
                                        for copy in results['failed']:
                                            st.write(f"  • {copy['model_id']}: {copy['error']}")
                                    
                                    if not results['successful'] and not results['failed']:
                                        st.info("No operations performed for this target.")
                                
                                print(f"Multi-target copy operation completed: {total_successful} successful, {total_failed} failed")
                                
                            except Exception as e:
                                st.error(f"An unexpected error occurred: {e}")
                                print(f"Unexpected error: {e}")