# SystemsManager-ChangeManagerPoC
システムズマネージャーのChangeManagerに必要な権限の検証

# 検証手順
## (1)事前設定
### (1)-(a) 作業環境の準備
下記を準備します。
* bashが利用可能な環境(LinuxやMacの環境)
* aws-cliのセットアップ
* AdministratorAccessポリシーが付与され実行可能な、aws-cliのProfileの設定

### (1)-(b) gitのclone
```shell
git clone https://github.com/Noppy/ECS-Fargate-CrossRegionTest.git
cd ECS-Fargate-CrossRegionTest
```

### (1)-(c) CLI実行用の事前準備
これ以降のAWS-CLIで共通で利用するパラメータを環境変数で設定しておきます。
```shell
export PROFILE="<検証を行う環境のプロファイル>"
export REGION="ap-northeast-1"

#プロファイルの動作テスト
aws --profile ${PROFILE} sts get-caller-identity
```

## (2) 検証環境準備
### (2)-(a) VPC作成
```shell
aws --profile ${PROFILE} --region ${REGION} \
    cloudformation create-stack \
        --stack-name SsmTest-VPC \
        --template-body "file://./cfn/vpc-2az-2subnets.yaml" \
        --parameters "file://./cfn/VPC.json" \
        --capabilities CAPABILITY_IAM ;
```
### (2)-(b) IAM & EC2作成
```shell
#最新のAmazon Linux2のAMI IDを取得
AL2_AMIID=$(aws --profile ${PROFILE} --region ${REGION} --output text \
    ec2 describe-images \
        --owners amazon \
        --filters 'Name=name,Values=amzn2-ami-hvm-2.0.????????.?-x86_64-gp2' \
                  'Name=state,Values=available' \
        --query 'reverse(sort_by(Images, &CreationDate))[:1].ImageId' );
echo "
AL2_AMIID = ${AL2_AMIID}"

#インスタンス作成
CFN_STACK_PARAMETERS='
[
  {
    "ParameterKey": "AmiId",
    "ParameterValue": "'"${AL2_AMIID}"'"
  }
]'

aws --profile ${PROFILE} --region ${REGION} \
    cloudformation create-stack \
        --stack-name SsmTest-IAM \
        --template-body "file://./cfn/iam_and_ec2.yaml" \
        --parameters "${CFN_STACK_PARAMETERS}" \
        --capabilities CAPABILITY_NAMED_IAM ;
```
### (2)-(c) IAM作成
#### (i)テスト用IAM Policy作成
SSM Automationでテスト用のRoleにアタッチ/デタッチするためのIAMポリシーをCLIで作成します。
```shell
POLICY='{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:Describe*",
        "ec2:List*"
      ],
      "Resource": "*"
    }
  ]
}'
aws --profile ${PROFILE} --region ${REGION} \
    iam create-policy \
        --policy-name "SsmTest-TestIamPolicy" \
        --policy-document "${POLICY}" 

#Attach Poicy    
export AccountID=$(aws --profile ${PROFILE} --output text sts get-caller-identity --query 'Account')

aws --profile ${PROFILE} --region ${REGION} \
    iam attach-role-policy \
        --role-name "Ec2-SsmTestRole" \
        --policy-arn "arn:aws:iam::${AccountID}:policy/SsmTest-TestIamPolicy"
```

#### (ii) SSM Automationの実行用ROLE作成
SSM Automationで実行するスクリプト内からIAM操作するためのIAMロールを作成します。
```shell
# ポリシーを設定
export AccountID=$(aws --profile ${PROFILE} --output text sts get-caller-identity --query 'Account')
ASSUMEROLE_POLICY='{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": "ssm.amazonaws.com"
            },
            "Action": "sts:AssumeRole",
            "Condition": {
                "StringEquals": {
                    "aws:SourceAccount": "'"${AccountID}"'"
                },
                "ArnLike": {
                    "aws:SourceArn": "arn:aws:ssm:*:'"${AccountID}"':automation-execution/*"
                }
            }
        }
    ]
}'

POLICY='{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowAttachDetach",
            "Effect": "Allow",
            "Action": [
                "iam:ListAttachedRolePolicies",
                "iam:AttachRolePolicy",
                "iam:DetachRolePolicy"
            ],
            "Resource": "*"
        }
    ]
}'
#IAMロール作成
aws --profile ${PROFILE} --region ${REGION} \
    iam create-role \
        --role-name "SsmTest-AutomatonRole" \
        --assume-role-policy-document "${ASSUMEROLE_POLICY}"

#インラインポリシーの作成
aws --profile ${PROFILE} --region ${REGION} \
    iam put-role-policy \
        --role-name "SsmTest-AutomatonRole" \
        --policy-name "AttachDetachIamPolicy" \
        --policy-document "${POLICY}"

```

## (3)SSM検証
### (3)-(a) SSM管理用ROLEにAssumeRole
管理者の権限分掌の確認のため、専用のロールで以下の作業を行う。
#### (i) AssumeRoleのクレデンシャル取得
```shell
export AccountID=$(aws --profile ${PROFILE} --output text sts get-caller-identity --query 'Account')

aws --profile ${PROFILE} \
    sts assume-role \
        --role-arn "arn:aws:iam::${AccountID}:role/SsmAdminRole" \
        --role-session-name "test"
```
新しいターミナルを起動し、以下のオペレーションを続けます。
以後の作業はこの新しいターミナルで実行します。
```shell
export AWS_ACCESS_KEY_ID="<上記の(3)-(a)で取得したAccessKeyIdを設定>"
export AWS_SECRET_ACCESS_KEY="<上記の(3)-(a)で取得したSecretAccessKeyを設定>"
export AWS_SESSION_TOKEN="<上記の(3)-(a)で取得したSessionTokenを設定>"

export AWS_DEFAULT_REGION="ap-northeast-1"

#クレデンシャル情報の動作テスト
 aws sts get-caller-identity
 ```
### (3)-(b) SSMドキュメントの作成
Automation実行のためのRunBookであるドキュメントを作成します。

#### (i) YAMLテンプレート準備
ドキュメントのYAMLファイルの実行ロール部分に、`(2)-(c)`の`(ii)`で作成したSSM Automation用ロールである`SsmTest-AutomatonRole`のARNを設定します。
```shell
export AccountID=$(aws --profile ${PROFILE} --output text sts get-caller-identity --query 'Account')
ROLE_ARN="arn:aws:iam::${AccountID}:role/SsmTest-AutomatonRole"

sed -e "s%<AssumeRoleArn>%${ROLE_ARN}%g" "ssm_src/Automation_ChangePolicy_template.yaml" > ./Automation_ChangePolicy.yaml
```
#### (ii) SSMドキュメント作成
SSMドキュメントを作成します。
```shell
aws ssm create-document \
    --name "SsmTest-AttachDetachIamPolicy" \
    --content "file://./Automation_ChangePolicy.yaml" \
    --document-type "Automation" \
    --document-format "YAML"
```

### (3)-(c) Automationの単独実行
```shell