[app]
title = Predictor PRO
package.name = predictorpro
package.domain = org.predictor

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,lic,txt
source.exclude_dirs = tests,bin,.buildozer,.github

version = 1.0

requirements = python3,kivy,flask,requests

orientation = portrait
fullscreen = 0

icon.filename = %(source.dir)s/icono.png

android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

android.api = 34
android.minapi = 24
android.ndk = 28c
android.ndk_api = 24

android.archs = arm64-v8a, armeabi-v7a

android.allow_backup = True
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 0
