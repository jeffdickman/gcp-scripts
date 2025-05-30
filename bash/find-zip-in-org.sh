#!/bin/bash

# Prompt for the Organization ID
read -p "Enter your Google Cloud Organization ID: " ORGANIZATION_ID

# Check if Organization ID is provided
if [ -z "$ORGANIZATION_ID" ]; then
  echo "Organization ID cannot be empty."
  exit 1
fi

# Create output file with timestamp
OUTPUT_FILE="archive_files_$(date +%Y%m%d_%H%M%S).txt"
echo "Results will be saved to: $OUTPUT_FILE"
echo "Project,Bucket,File Type,File Path" > "$OUTPUT_FILE"

echo "Fetching projects in organization: $ORGANIZATION_ID (this may take a while for large organizations)..."

# Get all project IDs in the organization, including those in folders
PROJECT_IDS=$(gcloud asset search-all-resources \
  --scope="organizations/$ORGANIZATION_ID" \
  --asset-types="cloudresourcemanager.googleapis.com/Project" \
  --format="value(name.basename())" \
  --quiet) # Added --quiet to suppress the progress bar for cleaner output to variable

# Check if any projects were found
if [ -z "$PROJECT_IDS" ]; then
  echo "No projects found in organization $ORGANIZATION_ID or you may not have the required permissions."
  exit 0
fi

echo "Found the following projects:"
echo "$PROJECT_IDS"
echo ""
echo "Searching for .zip files in buckets..."
echo "========================================"

# Loop through each project ID
for PROJECT_ID in $PROJECT_IDS
do
  echo "--- Project: $PROJECT_ID ---"
  # Set the active project for gsutil commands
  gcloud config set project "$PROJECT_ID" > /dev/null 2>&1
  if [ $? -ne 0 ]; then
    echo "Warning: Failed to set project $PROJECT_ID. Skipping."
    continue
  fi

  # List all buckets in the current project
  BUCKETS=$(gsutil ls 2>/dev/null)
  if [ -z "$BUCKETS" ]; then
    echo "  No buckets found in project $PROJECT_ID or insufficient permissions to list them."
  else
    BUCKET_FOUND_FOR_PROJECT=false
    # Loop through each bucket
    for BUCKET_URL in $BUCKETS
    do
      # Skip the specific bucket
      if [[ "$BUCKET_URL" == "gs://angels-bbops-video-dr/" ]]; then
        echo "  Skipping bucket: $BUCKET_URL"
        continue
      fi
      
      # Ensure it's actually a bucket (gsutil ls can return prefixes too)
      if [[ "$BUCKET_URL" == gs://* && "$BUCKET_URL" == */ ]]; then
        echo "  Scanning bucket: $BUCKET_URL"
        
        # Search for zip files
        ZIP_FILES=$(gsutil ls -r "${BUCKET_URL}**.zip" 2>/dev/null)
        if [ ! -z "$ZIP_FILES" ]; then
          BUCKET_FOUND_FOR_PROJECT=true
          echo "    Found .zip files:"
          while IFS= read -r ZIP_FILE; do
            echo "      $ZIP_FILE"
            echo "$PROJECT_ID,$BUCKET_URL,zip,$ZIP_FILE" >> "$OUTPUT_FILE"
          done <<< "$ZIP_FILES"
        fi

        # Search for tar files
        TAR_FILES=$(gsutil ls -r "${BUCKET_URL}**.tar" 2>/dev/null)
        if [ ! -z "$TAR_FILES" ]; then
          BUCKET_FOUND_FOR_PROJECT=true
          echo "    Found .tar files:"
          while IFS= read -r TAR_FILE; do
            echo "      $TAR_FILE"
            echo "$PROJECT_ID,$BUCKET_URL,tar,$TAR_FILE" >> "$OUTPUT_FILE"
          done <<< "$TAR_FILES"
        fi

        # Search for gz files
        GZ_FILES=$(gsutil ls -r "${BUCKET_URL}**.gz" 2>/dev/null)
        if [ ! -z "$GZ_FILES" ]; then
          BUCKET_FOUND_FOR_PROJECT=true
          echo "    Found .gz files:"
          while IFS= read -r GZ_FILE; do
            echo "      $GZ_FILE"
            echo "$PROJECT_ID,$BUCKET_URL,gz,$GZ_FILE" >> "$OUTPUT_FILE"
          done <<< "$GZ_FILES"
        fi

        if [ -z "$ZIP_FILES" ] && [ -z "$TAR_FILES" ] && [ -z "$GZ_FILES" ]; then
          echo "    No archive files found in $BUCKET_URL"
        fi
      fi
    done
    if ! $BUCKET_FOUND_FOR_PROJECT; then
        # This case is unlikely if $BUCKETS was not empty, but good for completeness
        # More likely, the loop for BUCKET_URL ran, but no zip files were found in any of them.
        : # Handled by individual "No .zip files found" messages
    fi
  fi
  echo "------------------------------------"
done

echo "========================================"
echo "Finished searching for archive files."
echo "Results have been saved to: $OUTPUT_FILE"