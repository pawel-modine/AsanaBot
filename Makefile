deploy: output.yml
	aws cloudformation deploy --template-file output.yml --stack-name asanabot --capabilities CAPABILITY_IAM

output.yml: code/githubhook.py _build/ template.yaml
	aws cloudformation package --template-file template.yaml --s3-bucket unidata-python --s3-prefix=asanabot/upload --output-template-file output.yml

_build/: code/sync.py code/stackoverflow.py requirements.txt
	rm -rf _build
	mkdir _build
	cp code/sync.py code/stackoverflow.py _build/
	python -m pip install -r requirements.txt -t _build
	find _build -maxdepth 1 -name '*.dist-info' -type d -print0 | xargs -0 rm -rf
	# urllib3 and six are included in the default env due to boto
	find _build -maxdepth 1 -name urllib3 -type d -print0 | xargs -0 rm -rf
	find _build -maxdepth 1 -name six.py -type f -delete

deploy_credentials: upload_github_secret upload_asana_tokens

upload_github_secret: github_secret
	aws ssm put-parameter --name /asanabot/GitHubToken --type SecureString --value `cat github_secret`

upload_asana_tokens: asana_client asana_token
	aws s3 cp asana_client s3://unidata-python/asanabot/asana_client
	aws s3 cp asana_token s3://unidata-python/asanabot/asana_token

deploy_config: upload_stackoverflow_config

upload_stackoverflow_config: stackoverflow_config.json
	aws s3 cp stackoverflow_config.json s3://unidata-python/asanabot/stackoverflow_config.json
