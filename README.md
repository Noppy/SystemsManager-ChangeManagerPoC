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
git clone https://github.com/Noppy/SystemsManager-ChangeManagerPoC.git
cd SystemsManager-ChangeManagerPoC
```

### (1)-(c) CLI実行用の事前準備
これ以降のAWS-CLIで共通で利用するパラメータを環境変数で設定しておきます。
```shell
export PROFILE="<検証を行う環境のAdministratorAccess権限があるプロファイル>"
export REGION="ap-northeast-1"

#プロファイルの動作テスト
aws --profile ${PROFILE} sts get-caller-identity
```

## (2) 検証環境準備
### (2)-(a) IAMユーザー/IAMロール作成
以下のリソースを作成します。
- IAMユーザ
    - `ChangeMgrAdmin` : SystemsManager管理者
    - `ChangeMgrTemplateApprover` : ChangeManagerの承認者
    - `ChangeMgrRequester` : ChangeManagerの申請者
- IAMロール
    - `SsmTest-AutomatonRole` : SSMのAutomationを実行するためのロール
    - `Ec2-SsmTestRole` : Automationで操作するデモ用IAMロール(このロールに特定のポリシーをアタッチ/デタッチする)
```shell
aws --profile ${PROFILE} --region ${REGION} \
    cloudformation create-stack \
        --stack-name SsmTest-IAM \
        --template-body "file://./cfn/iam.yaml" \
        --capabilities CAPABILITY_NAMED_IAM ;
```
### (2)-(b) ChangeManagerで必要となるServiceLinkedRole
この検証では、以下のServiceLinkedRoleが必要となる。
| サービスリンクドロール名                            | AWS Service名                      |
| ----------------------------------------------- | ---------------------------------- |
| AWSServiceRoleForSystemsManagerChangeManagement | changemanagement.ssm.amazonaws.com |
| AWSServiceRoleForAmazonSSM                      | ssm.amazonaws.com                  |

必要なServiceLinkedRoleの確認のため、検証用のロールにはCreateServiceLinkedRoleを付与していない。
必要に応じてAdministratorAccess権限の端末からServiceLinkedRoleを作成すること。
```shell
aws --profile ${PROFILE} iam create-service-linked-role --aws-service-name changemanagement.ssm.amazonaws.com
aws --profile ${PROFILE} iam create-service-linked-role --aws-service-name ssm.amazonaws.com
```

### (2)-(c) Automationで操作するIAMポリシー作成
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

## (3)SSM検証(Automation)
### (3)-(a) SSM管理用ユーザ(ChangeMgrAdmin)
管理者の権限分掌の確認のため、ChangeMgrAdminユーザーのアクセスキー/シークレットキーを生成し、以後の作業はChangeMgrAdminユーザーで作業を行います。
#### (i) ChangeMgrAdminでのCLI作業環境の準備
```shell
aws --profile ${PROFILE} \
    iam create-access-key \
        --user-name "ChangeMgrAdmin"
```
新しいターミナルを起動し、以下のオペレーションを続けます。
以後の作業はこの新しいターミナルで実行します。
```shell
#ディレクトリの移動
cd <SystemsManager-ChangeManagerPoCディレクトリに移動します>

#ChangeMgrAdminのアクセスキー&シークレットキー設定
export AWS_ACCESS_KEY_ID="上記の(3)-(a)で取得したAccessKeyIdを設定"
export AWS_SECRET_ACCESS_KEY="上記の(3)-(a)で取得したSecretAccessKeyを設定"

export AWS_DEFAULT_REGION="ap-northeast-1"

#クレデンシャル情報の動作テスト
 aws sts get-caller-identity
 ```

また確認のために`ChangeMgrAdmin`ユーザでマネージメントコンソールにログインしておくと良いです。
- URL: `https://ap-northeast-1.console.aws.amazon.com/systems-manager/home?region=ap-northeast-1#`
- アカウントID: `検証環境のAWSアカウントID(12桁の数字)`
- ユーザ: `ChangeMgrAdmin`
- PASS: `DemoPassword@`

### (3)-(b) SSMドキュメントの作成
Automation実行のためのRunBookであるドキュメントを作成します。
#### (i) YAMLテンプレート準備
ドキュメントのYAMLファイルの実行ロール部分に、`(2)-(c)`の`(ii)`で作成したSSM Automation用ロールである`SsmTest-AutomatonRole`のARNを設定します。
```shell
export AccountID=$(aws --output text sts get-caller-identity --query 'Account')
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
# Automationの実行
aws ssm start-automation-execution \
    --document-name "SsmTest-AttachDetachIamPolicy"

# Automationの実行状態の確認
aws ssm describe-automation-executions \
    --filter 'Key=ExecutionId,Values=<上記のAutomation実行時に表示されるExecutionIdを設定>'
```
検証用のAutomationの実行状態は以下のマネージメントコンソール画面から確認することができます。
- https://ap-northeast-1.console.aws.amazon.com/systems-manager/automation/executions?region=ap-northeast-1

またマネージメントコンソールで、Automation実行毎に対象IAMロールのポリシーがアタッチされたり解除されたりできていることを確認します。
- https://us-east-1.console.aws.amazon.com/iamv2/home?region=us-east-1#/roles/details/Ec2-SsmTestRole?section=permissions


## (4)SSM検証(Change Manager)

### (4)-(a) ChangeManger初期設定
```shell
export AccountID=$(aws --output text sts get-caller-identity --query 'Account')
#ユーザーID管理方式の設定(IAM or SSOでIAMを指定)
aws ssm update-service-setting \
    --setting-id "/ssm/change-management/identity-provider" \
    --setting-value "IAM"

#通知の無効化(詳細要調査)
aws ssm update-service-setting \
    --setting-id "/ssm/change-management/enable-email-notification" \
    --setting-value "False"

#テンプレートレビューワー通知設定
#(CloudFormationで作成したテンプレート承認者を追加)
aws ssm update-service-setting \
    --setting-id "/ssm/documents/automation/change-template/reviewers" \
    --setting-value '{
      "users":{
        "arn:aws:iam::'"${AccountID}"':user/ChangeMgrTemplateApprover": ""
      },
      "groups":{},
      "roles":{}
    }'

#変更フリーズイベントの承認者(なし)
aws ssm update-service-setting \
    --setting-id "/ssm/change-management/change-calendar/override-approver-list" \
    --setting-value '{}'

#すべてのテンプレートに対してモニターを必須にする
aws ssm update-service-setting \
    --setting-id "/ssm/change-management/require-rollback" \
    --setting-value 'False'

#使用前にテンプレートの確認と承認を要求
aws ssm update-service-setting \
    --setting-id "/ssm/change-management/require-approved-templates-only" \
    --setting-value 'True'
```


### (4)-(b) ChangeMangerテンプレートの作成
#### (i)テンプレートの作成(SsmAdminロール)
SsmAdminロールで、ChangeManagerのテンプレートを作成し、テンプレートのレビュー&承認依頼を行います。
```shell
#ドキュメントの作成
aws ssm create-document \
    --name "SsmTest-ChaneManagerTemplate-AttachDetachIamPolicy" \
    --content "file://./ssm_src/ChangeManager.yaml" \
    --document-type "Automation.ChangeTemplate" \
    --document-format "YAML"
```
テンプレート作成の詳細は下記ドキュメントを参照
- https://docs.aws.amazon.com/ja_jp/systems-manager/latest/userguide/change-templates-tools.html


#### (ii)テンプレートの承認依頼
本作業はマネージメントコンソールで作業します。Adminユーザー下記マネージメントコンソールを開きます。
- URL: `https://ap-northeast-1.console.aws.amazon.com/systems-manager/change-manager?region=ap-northeast-1#/change-template/view-details/SsmTest-ChaneManagerTemplate-AttachDetachIamPolicy/details`
- 実行ユーザ: `ChangeMgrAdmin`

作成したChangeManagerのテンプレー`SsmTest-ChaneManagerTemplate-AttachDetachIamPolicy`の右上の`レビューのために送信`(英語表記の場合は`Submit for review`)を押します。

### (4)-(c) テンプレートの承認
ChangeManagerの承認ユーザ(`ChangeMgrTemplateApprover`)でテンプレートを承認します。
管理者とは別の種類のブラウザ(例えば管理者がChromeだったらsafariで起動など)か、プライベートブラウジングモードでマネージメントコンソールを開きます。

- URL: `https://ap-northeast-1.console.aws.amazon.com/systems-manager/change-manager?region=ap-northeast-1#/change-template/view-details/SsmTest-ChaneManagerTemplate-AttachDetachIamPolicy/details`
- 実行ユーザ: `ChangeMgrTemplateApprover`
- PASS: `DemoPassword@`


マネージメントコンソールで開けたら、右上の`承認`(英語表記の場合は`Approve`)します。

### (4)-(d) 申請者からのChangeManagerの申請
ChangeManagerの申請ユーザ(`ChangeMgrRequester`)で申請し、承認ユーザ(`ChangeMgrTemplateApprover`)で承認します。

#### (i) 申請者(ChangeMgrRequester)による変更申請
管理者・承認者とは別の種類のブラウザ(例えば管理者がChromeだったらsafariで起動など)か、プライベートブラウジングモードでマネージメントコンソールを開きます。

- URL: `https://ap-northeast-1.console.aws.amazon.com/systems-manager/change-manager?region=ap-northeast-1#/dashboard/templates`
- 実行ユーザ: `ChangeMgrRequester`
- PASS: `DemoPassword@`

以下の手順で変更リクエストを作成します。
- Change Managerのダッシュボードの右上の`Create request`をクリックする
- テンプレートの中から`SsmTest-ChaneManagerTemplate-AttachDetachIamPolicy`を選択する
- `Basic change request details`
    - `Name`: リクエストに適当な名前を設定する。
- `Secify parameters`
    - 特に設定項目はない
- `Review and submit`
    - 内容を確認してサブミットする

#### (i) 承認者(ChangeMgrTemplateApprover)による承認
- URL: `https://ap-northeast-1.console.aws.amazon.com/systems-manager/change-manager?region=ap-northeast-1#/dashboard/templates`
- 実行ユーザ: `ChangeMgrTemplateApprover`
- PASS: `DemoPassword@`

以下の手順でリクエストを承認します。
- Change Managerのダッシュボードから`Approvals`を選択する。
- 該当のリクエスを選択し、内容確認後`Approve`する

