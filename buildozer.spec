[app]
title = Predictor PRO
package.name = predictorpro
package.domain = org.predictor
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,lic,txt
source.exclude_dirs = tests,bin,.buildozer
version = 1.0
requirements = python3,kivy,flask,flask-cors,requests,urllib3,chardet,idna,werkzeug,jinja2
orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/icono.png
android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.minapi = 21
android.api = 31
android.ndk = 25c