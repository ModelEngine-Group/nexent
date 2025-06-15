#!/bin/bash

source .env

# Add deployment mode selection function
select_deployment_mode() {
    echo "Please select deployment mode:"
    echo "1) Development mode - Expose all service ports for debugging"
    echo "2) Production mode - Only expose port 3000 for security"
    read -p "Enter your choice [1/2] (default: 1): " mode_choice

    case $mode_choice in
        2)
            export DEPLOYMENT_MODE="production"
            export COMPOSE_FILE="docker-compose.prod.yml"
            echo "Selected production mode deployment"
            ;;
        *)
            export DEPLOYMENT_MODE="development"
            export COMPOSE_FILE="docker-compose.yml"
            echo "Selected development mode deployment"
            ;;
    esac
}

generate_minio_ak_sk() {
  if [ "$(uname -s | tr '[:upper:]' '[:lower:]')" = "mingw" ] || [ "$(uname -s | tr '[:upper:]' '[:lower:]')" = "msys" ]; then
    # Windows
    ACCESS_KEY=$(powershell -Command "[System.Convert]::ToBase64String([System.Guid]::NewGuid().ToByteArray()) -replace '[^a-zA-Z0-9]', '' -replace '=.+$', '' | Select-Object -First 12")
    SECRET_KEY=$(powershell -Command '$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create(); $bytes = New-Object byte[] 32; $rng.GetBytes($bytes); [System.Convert]::ToBase64String($bytes)')
  else
    # Linux/Mac
    # Generate a random AK (12-character alphanumeric) and clean it
    ACCESS_KEY=$(openssl rand -hex 12 | tr -d '\r\n' | sed 's/[^a-zA-Z0-9]//g')

    # Generate a random SK (32-character high-strength random string) and clean it
    SECRET_KEY=$(openssl rand -base64 32 | tr -d '\r\n' | sed 's/[^a-zA-Z0-9+/=]//g')
  fi

  export MINIO_ACCESS_KEY=$ACCESS_KEY
  export MINIO_SECRET_KEY=$SECRET_KEY
}

clean() {
  export MINIO_ACCESS_KEY=
  export MINIO_SECRET_KEY=
  export DEPLOYMENT_MODE=
  export COMPOSE_FILE=
}

# Function to create a directory and set permissions
create_dir_with_permission() {
    local dir_path="$1"
    local permission="$2"

    # Check if parameters are provided
    if [ -z "$dir_path" ] || [ -z "$permission" ]; then
        echo "Error: Directory path and permission parameters are required." >&2
        return 1
    fi

    # Create the directory if it doesn't exist
    if [ ! -d "$dir_path" ]; then
        mkdir -p "$dir_path"
        if [ $? -ne 0 ]; then
            echo "Error: Failed to create directory $dir_path." >&2
            return 1
        fi
    fi

    # Set directory permissions
    chmod -R "$permission" "$dir_path"
    if [ $? -ne 0 ]; then
        echo "Error: Failed to set permissions $permission for directory $dir_path." >&2
        return 1
    fi

    echo "Directory $dir_path has been created and permissions set to $permission."
}

add_permission() {
  # Initialize the sql script permission
  chmod 644 "init.sql"

  create_dir_with_permission "elasticsearch" 775
  create_dir_with_permission "postgresql" 775
  create_dir_with_permission "minio" 775
  create_dir_with_permission "uploads" 777
}

install() {
  cd "$root_path"
  echo "Deploying services in ${DEPLOYMENT_MODE} mode..."
  docker-compose -p nexent -f "${COMPOSE_FILE}" up -d
}

# Main execution flow
echo "🚀 Nexent Deployment Script 🚀"
select_deployment_mode
add_permission
generate_minio_ak_sk
install
clean
echo "🚀 Deployment completed!"
echo "🔗 You can access the application at http://localhost:3000"