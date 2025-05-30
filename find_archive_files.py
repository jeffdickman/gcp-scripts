#!/usr/bin/env python3

import argparse
import csv
from datetime import datetime
import os
import sys
from typing import List, Dict, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
import subprocess
import json

class ArchiveFileFinder:
    def __init__(self, organization_id: str, output_file: Optional[str] = None):
        self.organization_id = organization_id
        self.output_file = output_file or f"archive_files_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.errors_file = f"permission_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        self.skipped_bucket = "gs://angels-bbops-video-dr/"
        self.archive_types = ['.zip', '.tar', '.tar.gz', '.gz']
        
    def check_auth(self) -> bool:
        """Check if user is authenticated with gcloud."""
        try:
            result = subprocess.run(
                ["gcloud", "auth", "list", "--filter=status:ACTIVE", "--format=value(account)"],
                capture_output=True,
                text=True,
                check=True
            )
            if not result.stdout.strip():
                print("Error: No active gcloud account found. Please run 'gcloud auth login' first.", file=sys.stderr)
                return False
            print(f"Using account: {result.stdout.strip()}")
            return True
        except subprocess.CalledProcessError as e:
            print(f"Error checking authentication: {e.stderr}", file=sys.stderr)
            return False

    def run_gcloud_command(self, command: List[str]) -> Tuple[str, bool]:
        """Run a gcloud command and return its output and success status."""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip(), True
        except subprocess.CalledProcessError as e:
            return e.stderr, False

    def get_projects(self) -> List[str]:
        """Get all projects in the organization."""
        print(f"Fetching projects in organization: {self.organization_id}...")
        command = [
            "gcloud", "asset", "search-all-resources",
            f"--scope=organizations/{self.organization_id}",
            "--asset-types=cloudresourcemanager.googleapis.com/Project",
            "--format=value(name.basename())",
            "--quiet"
        ]
        projects, success = self.run_gcloud_command(command)
        if not success or not projects:
            print("No projects found. Please ensure you have the following permissions:")
            print("- roles/asset.viewer")
            print("- roles/cloudasset.viewer")
            print("- roles/resourcemanager.organizationViewer")
            sys.exit(1)
        return [p for p in projects.split('\n') if p]

    def get_buckets(self, project_id: str) -> Tuple[List[str], bool]:
        """Get all buckets in a project. Returns (buckets, has_permission)."""
        try:
            # First check if we can set the project
            _, success = self.run_gcloud_command(["gcloud", "config", "set", "project", project_id])
            if not success:
                return [], False

            # Then check if we can list buckets
            buckets, success = self.run_gcloud_command(["gsutil", "ls"])
            if not success:
                return [], False

            bucket_list = [b for b in buckets.split('\n') if b and b.endswith('/')]
            print(f"  Found {len(bucket_list)} buckets in project {project_id}")
            for bucket in bucket_list:
                print(f"    Bucket: {bucket}")
            return bucket_list, True
        except Exception as e:
            print(f"  Error getting buckets for project {project_id}: {str(e)}")
            return [], False

    def search_bucket(self, bucket_url: str) -> List[Dict[str, str]]:
        """Search a bucket for archive files."""
        if bucket_url == self.skipped_bucket:
            print(f"Skipping bucket: {bucket_url}")
            return []

        # Special handling for the known bucket
        is_known_bucket = "bkt-prj-b-seed-tfstate-b052" in bucket_url
        if is_known_bucket:
            print(f"\nDEBUG: Found known bucket: {bucket_url}")
            print("Attempting to list all files in this bucket...")
            
            # First try a simple ls to see what's in the root
            try:
                root_files, success = self.run_gcloud_command(["gsutil", "ls", bucket_url])
                if success and root_files:
                    print("Files in root directory:")
                    for file in root_files.split('\n'):
                        if file:
                            print(f"  {file}")
            except Exception as e:
                print(f"Error listing root files: {str(e)}")

        results = []
        # First try a broad search to see what files exist
        try:
            print(f"    Listing all files in bucket: {bucket_url}")
            # Try different patterns for the broad search
            broad_patterns = [
                f"{bucket_url}**",  # Original pattern
                f"{bucket_url}*",   # Simple pattern
                f"{bucket_url}**/*" # Alternative pattern
            ]
            
            for pattern in broad_patterns:
                print(f"    Trying broad pattern: {pattern}")
                all_files, success = self.run_gcloud_command(["gsutil", "ls", "-r", pattern])
                if success and all_files:
                    print(f"    Found {len(all_files.split('\n'))} total files with pattern {pattern}")
                    # Print first few files for debugging
                    for file in all_files.split('\n')[:5]:
                        if file:
                            print(f"    Sample file: {file}")
                else:
                    print(f"    No files found with pattern {pattern} or error occurred")
        except Exception as e:
            print(f"    Error listing files: {str(e)}")

        # Now search for specific file types
        for ext in self.archive_types:
            try:
                # Try different search patterns
                patterns = [
                    f"{bucket_url}**{ext}",    # Original pattern
                    f"{bucket_url}*{ext}",     # Simple pattern
                    f"{bucket_url}**/*{ext}",  # Alternative pattern
                    f"{bucket_url}*/*{ext}",   # Another alternative
                    f"{bucket_url}**/*.{ext}"  # Pattern with dot
                ]
                
                for pattern in patterns:
                    print(f"    Trying pattern: {pattern}")
                    files, success = self.run_gcloud_command(["gsutil", "ls", "-r", pattern])
                    if not success:
                        print(f"    Error with pattern {pattern}: {files}")
                        continue
                    if files:
                        print(f"    Found {len(files.split('\n'))} {ext} files with pattern {pattern}")
                        for file_path in files.split('\n'):
                            if file_path:
                                results.append({
                                    'file_type': ext[1:],  # Remove the dot
                                    'file_path': file_path
                                })
                    else:
                        print(f"    No {ext} files found with pattern {pattern}")
            except subprocess.CalledProcessError as e:
                print(f"    Error searching for {ext} files: {str(e)}")
                continue
        return results

    def process_project(self, project_id: str) -> Tuple[List[Dict[str, str]], bool]:
        """Process a single project and its buckets. Returns (results, has_permission)."""
        print(f"--- Project: {project_id} ---")
        results = []
        buckets, has_permission = self.get_buckets(project_id)
        
        if not has_permission:
            print(f"  Permission denied for project {project_id}")
            with open(self.errors_file, 'a') as f:
                f.write(f"{project_id}\n")
            return results, False
        
        if not buckets:
            print(f"  No buckets found in project {project_id}")
            return results, True

        for bucket_url in buckets:
            print(f"  Scanning bucket: {bucket_url}")
            bucket_results = self.search_bucket(bucket_url)
            
            for result in bucket_results:
                results.append({
                    'project_id': project_id,
                    'bucket_url': bucket_url,
                    **result
                })

        return results, True

    def run(self):
        """Main execution method."""
        # Check authentication first
        if not self.check_auth():
            sys.exit(1)

        # Create output file and write header
        with open(self.output_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['project_id', 'bucket_url', 'file_type', 'file_path'])
            writer.writeheader()

        # Create empty errors file
        with open(self.errors_file, 'w') as f:
            f.write("# Projects with permission issues\n")

        # Get all projects
        projects = self.get_projects()
        if not projects:
            print(f"No projects found in organization {self.organization_id} or you may not have the required permissions.")
            return

        print(f"Found {len(projects)} projects")
        print("Searching for archive files in buckets...")
        print("========================================")

        # Process projects in parallel
        all_results = []
        permission_issues = 0
        with ThreadPoolExecutor(max_workers=5) as executor:
            project_results = list(executor.map(self.process_project, projects))
            for results, has_permission in project_results:
                all_results.extend(results)
                if not has_permission:
                    permission_issues += 1

        # Write results to file
        with open(self.output_file, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['project_id', 'bucket_url', 'file_type', 'file_path'])
            writer.writerows(all_results)

        print("========================================")
        print(f"Finished searching for archive files.")
        print(f"Found {len(all_results)} archive files.")
        print(f"Found {permission_issues} projects with permission issues.")
        print(f"Results have been saved to: {self.output_file}")
        if permission_issues > 0:
            print(f"Projects with permission issues have been saved to: {self.errors_file}")

def main():
    parser = argparse.ArgumentParser(description='Search for archive files in GCP organization buckets.')
    parser.add_argument('--org-id', required=True, help='Google Cloud Organization ID')
    parser.add_argument('--output', help='Output file path (optional)')
    
    args = parser.parse_args()
    
    finder = ArchiveFileFinder(args.org_id, args.output)
    finder.run()

if __name__ == "__main__":
    main() 