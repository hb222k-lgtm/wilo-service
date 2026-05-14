#!/bin/bash
cd "$(dirname "$0")"
echo "필요한 패키지 설치 중..."
pip3 install -r requirements.txt -q
echo ""
python3 app.py
