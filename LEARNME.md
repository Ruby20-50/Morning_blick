### cloudflare tunneling 
cloudflared --version
cloudflared tunnel --url http://localhost:8000

### 


### do a summary of the project and chosen folders :
for d in app/api app/schemas app/config app/services app/main.py app/scripts app/templates; do find $d -name "*.py" | sort | while read f; do echo "=== $f ==="; cat "$f"; done; done > ~/code_uni.txt

### do a tree description 
find . \( -path ./.venv -o -path ./.git -o -name __pycache__ -o -name .pytest_cache \) -prune -o -type f -print | sort > ~/tree_uni.txt

### secure your secrets :
grep -iE "api[_-]?key|secret|token|password" ~/code_uni.txt 
