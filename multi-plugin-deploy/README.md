# PPI Multi Plugin Deploy

这个目录用于把同一套 PPI Calculator 核心代码部署成 3 个飞书多维表格插件：

- `skin`
- `hair`
- `makeup`

三套插件的核心 Python 计算逻辑完全一样，只通过部署配置区分：

- 前端静态页面入口
- 后端监听端口
- 后端 trigger token
- nginx 路由路径
- 未来可选的 RSP 表名或字段名

## 1. 目录结构

```text
multi-plugin-deploy/
  frontend/
    skin/index.html
    hair/index.html
    makeup/index.html
  backend/
    env/
      ppi-skin.env.example
      ppi-hair.env.example
      ppi-makeup.env.example
    systemd/
      ppi-backend-skin.service
      ppi-backend-hair.service
      ppi-backend-makeup.service
    nginx/
      ppi-multi-plugin-nginx.conf
  scripts/
    install_multi_backend_on_server.sh
```

## 2. 推荐部署架构

服务器上只保留一份核心代码目录：

```text
/opt/ppi
```

然后开 3 个后端服务：

```text
ppi-backend-skin   -> 127.0.0.1:8001
ppi-backend-hair   -> 127.0.0.1:8002
ppi-backend-makeup -> 127.0.0.1:8003
```

nginx 对外仍然只暴露 80 端口，并按路径转发：

```text
http://115.190.197.231/skin/run-ppi   -> 127.0.0.1:8001/run-ppi
http://115.190.197.231/hair/run-ppi   -> 127.0.0.1:8002/run-ppi
http://115.190.197.231/makeup/run-ppi -> 127.0.0.1:8003/run-ppi
```

帽子云上建 3 个静态应用：

```text
ppi-skin    -> 上传 frontend/skin/index.html
ppi-hair    -> 上传 frontend/hair/index.html
ppi-makeup  -> 上传 frontend/makeup/index.html
```

每个帽子云应用配置一个反向代理：

```text
前端请求路径: /skin*
代理协议: HTTP
反向代理地址: 115.190.197.231
代理 HOST: 代理地址域名或者 IP
```

hair/makeup 同理改成 `/hair*`、`/makeup*`。

## 3. 本地先准备 token

给 3 个插件分别生成不同 token。示例：

```bash
openssl rand -hex 32
openssl rand -hex 32
openssl rand -hex 32
```

把生成的 token 分别填到：

```text
backend/env/ppi-skin.env.example
backend/env/ppi-hair.env.example
backend/env/ppi-makeup.env.example
```

并同步填进对应前端文件：

```text
frontend/skin/index.html
frontend/hair/index.html
frontend/makeup/index.html
```

搜索 `REPLACE_WITH_..._TOKEN` 即可。

## 4. 上传到服务器

在 Mac 本地执行：

```bash
cd /Users/shuoyang/PPI

scp -r multi-plugin-deploy root@115.190.197.231:/tmp/
scp ppi-hotfix-prompt-v2-user-inputs.tar.gz root@115.190.197.231:/tmp/

ssh root@115.190.197.231
```

进入服务器后执行：

```bash
cd /opt/ppi
tar -xzf /tmp/ppi-hotfix-prompt-v2-user-inputs.tar.gz -C /opt/ppi

mkdir -p /opt/ppi/env
cp /tmp/multi-plugin-deploy/backend/env/ppi-skin.env.example /opt/ppi/env/ppi-skin.env
cp /tmp/multi-plugin-deploy/backend/env/ppi-hair.env.example /opt/ppi/env/ppi-hair.env
cp /tmp/multi-plugin-deploy/backend/env/ppi-makeup.env.example /opt/ppi/env/ppi-makeup.env
```

然后编辑这三个 env 文件，把里面的 `REPLACE_WITH_..._TOKEN` 替换成真实 token：

```bash
nano /opt/ppi/env/ppi-skin.env
nano /opt/ppi/env/ppi-hair.env
nano /opt/ppi/env/ppi-makeup.env
```

## 5. 安装 systemd 服务和 nginx

服务器上继续执行：

```bash
cp /tmp/multi-plugin-deploy/backend/systemd/ppi-backend-skin.service /etc/systemd/system/
cp /tmp/multi-plugin-deploy/backend/systemd/ppi-backend-hair.service /etc/systemd/system/
cp /tmp/multi-plugin-deploy/backend/systemd/ppi-backend-makeup.service /etc/systemd/system/

cp /tmp/multi-plugin-deploy/backend/nginx/ppi-multi-plugin-nginx.conf /etc/nginx/sites-available/ppi-multi-plugin
ln -sf /etc/nginx/sites-available/ppi-multi-plugin /etc/nginx/sites-enabled/ppi-multi-plugin
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable ppi-backend-skin ppi-backend-hair ppi-backend-makeup
systemctl restart ppi-backend-skin ppi-backend-hair ppi-backend-makeup

nginx -t
systemctl reload nginx
```

## 6. 检查服务器是否成功

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8002/health
curl http://127.0.0.1:8003/health

curl http://115.190.197.231/skin/health
curl http://115.190.197.231/hair/health
curl http://115.190.197.231/makeup/health
```

都返回 `{"ok": true, ...}` 就说明后端和 nginx 都通了。

## 7. 帽子云前端部署

分别把以下目录作为 3 个静态站点部署：

```text
multi-plugin-deploy/frontend/skin
multi-plugin-deploy/frontend/hair
multi-plugin-deploy/frontend/makeup
```

每个站点都只有一个 `index.html`。

帽子云反向代理建议：

skin 应用：

```text
前端请求路径: /skin*
代理协议: HTTP
反向代理地址: 115.190.197.231
代理 HOST: 代理地址域名或者 IP
```

hair 应用：

```text
前端请求路径: /hair*
代理协议: HTTP
反向代理地址: 115.190.197.231
代理 HOST: 代理地址域名或者 IP
```

makeup 应用：

```text
前端请求路径: /makeup*
代理协议: HTTP
反向代理地址: 115.190.197.231
代理 HOST: 代理地址域名或者 IP
```

## 8. 飞书插件 URL

帽子云部署完成后，飞书插件 URL 分别填对应静态站点首页，例如：

```text
https://your-skin-app.maozi.io/
https://your-hair-app.maozi.io/
https://your-makeup-app.maozi.io/
```

前端已经内置了默认 backend 和 token。如果临时调试，也可以用 query 参数覆盖：

```text
https://your-skin-app.maozi.io/?backend=https://your-skin-app.maozi.io/skin/run-ppi&token=TOKEN
```

## 9. GitHub 建议

建议仓库结构保持这样：

```text
ppi-calculator/
  PPI-deploy-20260506-154109/
  multi-plugin-deploy/
  README.md
```

不要上传这些内容：

```text
.env
.venv/
__pycache__/
*.pyc
服务器登陆密码
*.tar.gz
*.xlsx
```

如果你希望把 Excel 样例也放 GitHub，建议新建 `samples/`，并确认里面没有敏感数据。
