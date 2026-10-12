#!/usr/bin/env bash
# Print the URL of the running app task. Fargate gives each task a new
# public IP, so this looks it up rather than storing it anywhere.
set -euo pipefail
cd "$(dirname "$0")"

cluster=$(terraform output -raw cluster)
service=$(terraform output -raw service)

task=$(aws ecs list-tasks --cluster "$cluster" --service-name "$service" \
  --desired-status RUNNING --query 'taskArns[0]' --output text)
if [[ -z "$task" || "$task" == "None" ]]; then
  echo "No running task. Start one with: make aws-start" >&2
  exit 1
fi

eni=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task" \
  --query "tasks[0].attachments[0].details[?name=='networkInterfaceId'].value | [0]" --output text)
ip=$(aws ec2 describe-network-interfaces --network-interface-ids "$eni" \
  --query 'NetworkInterfaces[0].Association.PublicIp' --output text)

echo "http://$ip:8000"
