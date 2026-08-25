# 테스트 fixture

이 디렉터리의 오디오는 실제 사람의 음성이 아닙니다. 외부 네트워크와 GPU 없이 입력 감지, ffprobe, 콘텐츠 해시, fake AI 파이프라인을 검증하기 위해 FFmpeg의 합성 소스로 생성했습니다.

```sh
ffmpeg -f lavfi -i 'anullsrc=r=44100:cl=mono' -t 2 -c:a aac -b:a 64k -map_metadata -1 -fflags +bitexact -flags:a +bitexact complete.m4a
ffmpeg -f lavfi -i 'sine=frequency=440:sample_rate=44100' -t 2 -c:a aac -b:a 64k -map_metadata -1 -fflags +bitexact -flags:a +bitexact speaker-review.m4a
```

- `complete.m4a`: 자동 요약까지 완료되는 fake 흐름
- `speaker-review.m4a`: 화자 검토에서 멈추는 fake 흐름
- `corrupt.m4a`: ffprobe가 거부해야 하는 의도적으로 손상된 입력
- `manifest.json`: fixture 해시와 선택할 기대 결과
- `expected/*.json`: fake 어댑터의 정규화된 기대 결과
