#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import boto3

ROLE_NAME = "Ec2-SsmTestRole"
POLICY_NAME = "SsmTest-TestIamPolicy"

def script_handler(events, context):
  # Get Session
  sts = boto3.client('sts')
  iam = boto3.client('iam')

  # Get Account ID
  ret = sts.get_caller_identity()
  awsaccuntid = ret['Account']

  # Get a list of policies attached to the ROLE_NAME role.
  policies = iam.list_attached_role_policies(
    RoleName = ROLE_NAME,
  )

  # Check Policy
  policy_exist = False
  for policy in policies['AttachedPolicies']:
      if policy['PolicyName'] == POLICY_NAME:
        policy_exist = True

  # Attach/Detach a policy
  policy_arn = 'arn:aws:iam::{0:s}:policy/{1:s}'.format(awsaccuntid, POLICY_NAME)
  if policy_exist:
      print("ある！！")
      iam.detach_role_policy(
        RoleName  = ROLE_NAME,
        PolicyArn =  policy_arn
      )

  else:
      print("ないーーーーー")
      iam.attach_role_policy(
        RoleName  = ROLE_NAME,
        PolicyArn =  policy_arn
      )

if __name__ == "__main__":
   script_handler("aaa","bbb")