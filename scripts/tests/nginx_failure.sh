#!/usr/bin/env bash
# Run only in a disposable test container. All service commands are fake.
set -Eeuo pipefail
[[ -f /.dockerenv && ${1:-} == --isolated-test-container ]] || exit 2
workspace=$(mktemp -d)
mkdir -p "$workspace/scripts" "$workspace/bin" /etc/nginx/sites-available /etc/nginx/sites-enabled
cp scripts/{lib.sh,env.py,nginx.sh} "$workspace/scripts/"
cp .env.production.example "$workspace/"
python3 "$workspace/scripts/env.py" init "$workspace/.env" --demo --domain test.example.com
export PATH="$workspace/bin:$PATH"
export COUNTER="$workspace/count"
cat > "$workspace/bin/nginx" <<'EOF'
#!/bin/bash
count=0
[[ ! -f "$COUNTER" ]] || count=$(cat "$COUNTER")
count=$((count + 1))
echo "$count" > "$COUNTER"
[[ $count != 2 ]]
EOF
for tool in certbot curl openssl systemctl; do
    printf '#!/bin/bash\nexit 0\n' > "$workspace/bin/$tool"
done
chmod +x "$workspace/bin/"*
site=/etc/nginx/sites-available/edunexa-test.example.com.conf
printf '# Managed by EduNexa scripts/nginx.sh for test.example.com\n# previous config\n' > "$site"
cp "$site" "$workspace/before"
set +e
bash "$workspace/scripts/nginx.sh" --apply --obtain-certificate --email test@example.com
result=$?
set -e
[[ $result != 0 ]]
cmp "$site" "$workspace/before"
[[ ! -L /etc/nginx/sites-enabled/edunexa-test.example.com.conf ]]
echo 'PASS: mocked nginx -t failure restores previous vhost and removes newly created enable symlink.'
