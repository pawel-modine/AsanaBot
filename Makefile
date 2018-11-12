deploy: output.yml
	aws cloudformation deploy --template-file output.yml --stack-name asanabot --capabilities CAPABILITY_IAM

output.yml: code/event_handler.py _build/ template.yaml
	aws cloudformation package --template-file template.yaml --s3-bucket unidata-python --s3-prefix=asanabot/upload --output-template-file output.yml

_build/: code/sync.py requirements.txt
	rm -rf _build
	mkdir _build
	cp code/sync.py _build/
	pip install -r requirements.txt -t _build
	find _build -maxdepth 1 -name '*.dist-info' -type d -print0 | xargs -0 rm -rf

deploy_credentials: upload_github_secret upload_asana_tokens

upload_github_secret: github_secret
	aws s3 cp github_secret s3://unidata-python/asanabot/github

upload_asana_tokens: asana_client asana_token
	aws s3 cp asana_client s3://unidata-python/asanabot/asana_client
	aws s3 cp asana_token s3://unidata-python/asanabot/asana_token
