import streamlit as st
import os
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
        st.info(f"🔑 Connecting to Key Vault: {key_vault_url}")
        credential = DefaultAzureCredential()
        client = SecretClient(vault_url=key_vault_url, credential=credential)
        
        # Test the connection by trying to list secrets (this will fail if no permissions, but connection works)
        try:
            # This will test if we can authenticate to the Key Vault
            list(client.list_properties_of_secrets(max_page_size=1))
            st.success("✅ Successfully connected to Key Vault with DefaultAzureCredential")
        except Exception as perm_error:
            st.warning(f"⚠️ Connected to Key Vault but may have limited permissions: {perm_error}")
            
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
        st.success(f"✅ Successfully retrieved secret '{secret_name}' from Key Vault")
        # Only show first few characters for security
        masked_value = secret.value[:8] + "..." if len(secret.value) > 8 else "***"
        st.info(f"Secret value starts with: {masked_value}")
        return secret.value
    except Exception as e:
        st.error(f"❌ Failed to retrieve secret '{secret_name}': {e}")
        return None

def test_di_connection(di_client):
    """Test the Document Intelligence client connection."""
    try:
        # Try to get resource details - this is a lightweight operation
        resource_details = di_client.get_resource_details()
        st.success(f"✅ Document Intelligence connection successful!")
        st.info(f"📊 Resource details: Custom models limit: {resource_details.custom_document_models.limit}, Used: {resource_details.custom_document_models.count}")
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
        st.info(f"🔗 Creating DI client for endpoint: {endpoint}")
        client = DocumentIntelligenceAdministrationClient(endpoint=endpoint, credential=AzureKeyCredential(key))
        st.success("✅ Successfully created DocumentIntelligence client")
        return client
    except Exception as e:
        st.error(f"❌ Failed to create DI client for endpoint {endpoint}: {e}")
        return None

# --- Get configuration from environment variables ---
source_endpoint = os.getenv("SOURCE_ENDPOINT")
source_kv_url = os.getenv("SOURCE_KV_URL")
source_secret_name = os.getenv("SOURCE_SECRET_NAME")
target_endpoint = os.getenv("TARGET_ENDPOINT")
target_kv_url = os.getenv("TARGET_KV_URL")
target_secret_name = os.getenv("TARGET_SECRET_NAME")

# --- Configuration Validation ---
st.subheader("🔧 Configuration Status")
config_col1, config_col2 = st.columns(2)

with config_col1:
    st.write("**Source Configuration:**")
    st.write(f"✅ Endpoint: {source_endpoint}" if source_endpoint else "❌ SOURCE_ENDPOINT not set")
    st.write(f"✅ Key Vault: {source_kv_url}" if source_kv_url else "❌ SOURCE_KV_URL not set")
    st.write(f"✅ Secret Name: {source_secret_name}" if source_secret_name else "❌ SOURCE_SECRET_NAME not set")

with config_col2:
    st.write("**Target Configuration:**")
    st.write(f"✅ Endpoint: {target_endpoint}" if target_endpoint else "❌ TARGET_ENDPOINT not set")
    st.write(f"✅ Key Vault: {target_kv_url}" if target_kv_url else "❌ TARGET_KV_URL not set")
    st.write(f"✅ Secret Name: {target_secret_name}" if target_secret_name else "❌ TARGET_SECRET_NAME not set")

st.markdown("---")


# --- Session State Initialization ---
if 'models_list' not in st.session_state:
    st.session_state.models_list = []

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
                                    st.session_state.models_list = [m for m in models]
                                    if st.session_state.models_list:
                                        st.success(f"Found {len(st.session_state.models_list)} models.")
                                        # Show model details in an expandable section
                                        with st.expander("📋 Model Details"):
                                            for model in st.session_state.models_list:
                                                st.write(f"• **{model.model_id}** - Created: {model.created_date_time.strftime('%Y-%m-%d %H:%M') if hasattr(model, 'created_date_time') and model.created_date_time else 'Unknown'}")
                                    else:
                                        st.info("No custom models found on the source resource.")
                                except Exception as e:
                                    st.error(f"An error occurred while fetching models: {e}")
                        else:
                            st.error("Cannot proceed with model listing due to connection issues.")

# --- Target Column ---
with col2:
    st.header("Target Resource")
    st.write(f"**Endpoint:** `{target_endpoint}`")
    st.write(f"**Key Vault:** `{target_kv_url}`")
    
    st.markdown("---")

    if not st.session_state.models_list:
        st.info("Fetch models from a source resource to see copy options.")
    else:
        model_options = {f"{model.model_id} (Created: {model.created_date_time.strftime('%Y-%m-%d') if hasattr(model, 'created_date_time') and model.created_date_time else 'Unknown'})": model.model_id for model in st.session_state.models_list}
        selected_model_display = st.selectbox("Select Model to Copy", options=model_options.keys())
        model_id_to_copy = model_options[selected_model_display]
        new_model_id = st.text_input("Enter New Model ID for Target", value=f"{model_id_to_copy}-copy")

        if st.button("Copy Model to Target", use_container_width=True, type="primary"):
            if not all([target_endpoint, target_kv_url, target_secret_name, model_id_to_copy, new_model_id]):
                st.warning("Please ensure TARGET_ENDPOINT, TARGET_KV_URL, and TARGET_SECRET_NAME are set in your .env file and select a model.")
            else:
                # Get source key again for the copy operation
                source_kv_client = get_secret_client(source_kv_url)
                source_key = get_api_key_from_kv(source_kv_client, source_secret_name) if source_kv_client else None

                # Get target key
                target_kv_client = get_secret_client(target_kv_url)
                target_key = get_api_key_from_kv(target_kv_client, target_secret_name) if target_kv_client else None

                if source_key and target_key:
                    source_di_client = get_admin_client(source_endpoint, source_key)
                    target_di_client = get_admin_client(target_endpoint, target_key)

                    if source_di_client and target_di_client:
                        with st.status(f"Copying '{model_id_to_copy}' to '{new_model_id}'...", expanded=True) as status:
                            try:
                                st.write("Copying models between Document Intelligence resources...")
                                st.write("Note: Direct model copying may require REST API calls.")
                                st.write("For now, this is a placeholder for the copy functionality.")
                                
                                # TODO: Implement actual model copying using REST API
                                # The Azure Document Intelligence SDK may not expose all copy methods
                                # Consider using direct REST API calls for model copying
                                
                                st.warning("Model copying functionality needs to be implemented using REST API calls.")
                                st.info(f"Would copy model '{model_id_to_copy}' to '{new_model_id}'")
                                
                            except HttpResponseError as e:
                                st.error(f"An error occurred during the copy operation: {e.message}")
                            except Exception as e:
                                st.error(f"An unexpected error occurred: {e}")