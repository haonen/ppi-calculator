# GitHub Setup

建议把 `/Users/shuoyang/PPI` 作为仓库根目录上传。

## 初始化仓库

```bash
cd /Users/shuoyang/PPI
git init
git add .gitignore PPI-deploy-20260506-154109 multi-plugin-deploy
git status
git commit -m "Initial PPI calculator multi-plugin deployment"
```

## 关联 GitHub 远程仓库

先在 GitHub 网页上新建一个私有仓库，例如：

```text
ppi-calculator
```

然后本地执行：

```bash
git remote add origin git@github.com:YOUR_ACCOUNT/ppi-calculator.git
git branch -M main
git push -u origin main
```

如果你使用 HTTPS：

```bash
git remote add origin https://github.com/YOUR_ACCOUNT/ppi-calculator.git
git branch -M main
git push -u origin main
```

## 不要提交的内容

这些内容已经在根目录 `.gitignore` 里排除了：

```text
.env
.env.*
.venv/
__pycache__/
*.pyc
*.tar.gz
*.zip
*.xlsx
服务器登陆密码
```

注意：真实 Feishu、Loreal GPT、trigger token 都不要提交。GitHub 里只放 `.env.example` 和 `*.env.example`。

## 从另一台电脑修改

```bash
git clone git@github.com:YOUR_ACCOUNT/ppi-calculator.git
cd ppi-calculator
```

然后自己补本地 `.env`，不要 commit。
