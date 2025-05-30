#!/bin/bash

# Prompt for the Organization ID
read -p "Enter your Google Cloud Organization ID: " ORGANIZATION_ID

# Check if Organization ID is provided
if [ -z "$ORGANIZATION_ID" ]; then
  echo "Organization ID cannot be empty."
  exit 1
fi

echo "Fetching projects in organization: $ORGANIZATION_ID (this may take a while for large organizations)..."

# Get all project IDs in the organization, including those in folders
PROJECT_IDS=$(gcloud asset search-all-resources \
  --scope="organizations/$ORGANIZATION_ID" \
  --asset-types="cloudresourcemanager.googleapis.com/Project" \
  --format="value(name.basename())")

# Check if any projects were found
if [ -z "$PROJECT_IDS" ]; then
  echo "No projects found in organization $ORGANIZATION_ID or you may not have the required permissions."
  exit 0
fi

echo "Found the following projects:"
echo "$PROJECT_IDS"
echo ""
echo "Listing buckets for each project..."
echo "------------------------------------"

# Loop through each project ID and list its buckets
for PROJECT_ID in $PROJECT_IDS
do
  echo "Buckets in project: $PROJECT_ID"
  # gcloud storage ls --project="$PROJECT_ID"
  # Using gsutil as gcloud storage ls --project is not the standard way,
  # and gsutil ls is more common for listing buckets within a specific project context.
  # Note: gsutil will use the currently active project if --project is not available for `ls` directly.
  # To ensure we list for the correct project, we can set the project for each iteration.
  gcloud config set project "$PROJECT_ID" > /dev/null 2>&1
  gsutil ls
  echo "------------------------------------"
done

echo "Finished listing all buckets."