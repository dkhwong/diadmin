# Azure Document Intelligence Model Manager

A tool to list and copy custom models between Document Intelligence resources with support for multiple target environments.

## Features

- **Single Source, Multiple Targets**: Copy models from one source to up to 3 different target environments
- **Selective Copying**: Choose which models to copy and which target environments to copy to
- **Environment Management**: Support for Development, Staging, and Production environments
- **Secure Key Management**: Uses Azure Key Vault for API key storage
- **Batch Operations**: Copy multiple models to multiple targets in a single operation
- **Real-time Monitoring**: Track copy progress with detailed status updates

## Configuration

### Environment Variables

Create a `.env` file in the project root with the following configuration:

```env
# Source Document Intelligence Resource Configuration
SOURCE_ENDPOINT=https://your-source-di-resource.cognitiveservices.azure.com/
SOURCE_KV_URL=https://your-source-keyvault.vault.azure.net/
SOURCE_SECRET_NAME=your-source-di-api-key

# Target Environment 1 Configuration
TARGET1_ENDPOINT=https://your-target1-di-resource.cognitiveservices.azure.com/
TARGET1_KV_URL=https://your-target1-keyvault.vault.azure.net/
TARGET1_SECRET_NAME=your-target1-di-api-key
TARGET1_NAME=Development

# Target Environment 2 Configuration
TARGET2_ENDPOINT=https://your-target2-di-resource.cognitiveservices.azure.com/
TARGET2_KV_URL=https://your-target2-keyvault.vault.azure.net/
TARGET2_SECRET_NAME=your-target2-di-api-key
TARGET2_NAME=Staging

# Target Environment 3 Configuration
TARGET3_ENDPOINT=https://your-target3-di-resource.cognitiveservices.azure.com/
TARGET3_KV_URL=https://your-target3-keyvault.vault.azure.net/
TARGET3_SECRET_NAME=your-target3-di-api-key
TARGET3_NAME=Production
```

**Note**: You don't need to configure all 3 target environments. Configure only the ones you need.

### Azure Authentication

This tool uses `DefaultAzureCredential` to access Azure Key Vault. For local development:

1. Install Azure CLI: `az login`
2. Ensure your account has access to the Key Vaults specified in the configuration

## Usage

1. **Start the application**: `streamlit run app.py`
2. **Verify configuration**: Check that all your environments are properly configured
3. **Fetch source models**: Click "Get Models from Source" to load available models
4. **Check target environments**: Use the tabs to check existing models in each target environment
5. **Select models**: Choose which models you want to copy
6. **Configure copy settings**:
   - Add an optional suffix to copied model names
   - Select which target environments to copy to
7. **Execute copy**: Click the copy button to start the batch operation

## Features in Detail

### Multi-Target Support

- Configure up to 3 target environments (Development, Staging, Production)
- Customize environment names using `TARGET1_NAME`, `TARGET2_NAME`, `TARGET3_NAME`
- Selectively copy to specific target environments
- Each target environment is displayed in its own tab

### Smart Model Filtering

- Only shows models that don't already exist in any target environment
- Automatically filters out prebuilt models (only shows custom models)
- Sorts models by creation date (newest first)

### Batch Operations

- Copy multiple models to multiple targets in a single operation
- Real-time progress tracking for each model and target combination
- Comprehensive summary showing success/failure status for each target

### Error Handling

- Detailed error messages for authentication, authorization, and copy failures
- Operation timeout handling for long-running copy operations
- Retry logic for status checking

## Requirements

- Python 3.8+
- Streamlit
- Azure SDK for Python
- Azure CLI (for authentication)
- Access to Azure Document Intelligence resources
- Access to Azure Key Vault containing API keys

## Installation

```bash
pip install -r requirements.txt
```

## Security Notes

- API keys are stored securely in Azure Key Vault
- The application never displays full API keys in the UI
- All operations use secure Azure SDK clients
- Authentication is handled through Azure's identity system
