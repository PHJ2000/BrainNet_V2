# GPT-6 Astra 단독 vs Astra 지휘 + Luna 6개 비교

동일한 BrainNet 기능 과제를 같은 커밋에서 두 독립 worktree로 실행하는 로컬 비교 하네스다.

- `solo`: GPT-6 Astra `high` 한 명이 전체 구현과 검증 수행
- `multi`: GPT-6 Astra `high` 한 명이 계획·업무 배분·최종 검토만 수행하고, GPT-6 Luna `max` 6명이 모든 구현·수정·검증 수행
- 공통: 같은 `TASK.md`, workspace-write sandbox, 승인 없음, 커밋·푸시·개인 DB 변경 금지

[공식 모델 선택 문서](https://developers.openai.com/api/docs/guides/model-selection)는 Astra를 복잡한 종합 작업, Luna를 범위가 명확한 작업에 권장한다. 멀티 arm에서는 Astra가 저장소를 읽고 구조화된 여섯 개 작업을 만든다. 호스트가 그 계획을 Luna 세션 여섯 개에 순서대로 전달하고, 마지막 Luna가 누적 변경을 통합·수정·검증한다. 같은 Astra 세션은 변경된 결과를 읽고 최종 합격 여부만 판정한다. 중첩 CLI는 상위 Codex 실행 정책을 피하기 위해 자동화용 sandbox 우회 모드로 실행하지만, Astra 단계 전후의 Git diff와 untracked 파일 해시를 호스트가 비교한다. Astra가 worktree를 변경하면 즉시 실험을 무효 처리한다.

이 구조는 서로 다른 모델을 확실히 고정하고 실제 생성된 세션 ID를 검증한다. 멀티 arm의 성공 조건은 Astra 세션 1개·Astra turn 2개·서로 다른 Luna 세션 6개다.

## 준비 확인

```powershell
./experiments/codex-astra-vs-6-luna/check-environment.ps1
./experiments/codex-astra-vs-6-luna/prepare.ps1
```

두 번째 명령은 `.tools/model-comparison/<run-id>/` 아래에 worktree 두 개와 `manifest.json`을 만든다. 현재 브랜치가 깨끗해야 하며 기준 커밋을 두 브랜치에 똑같이 고정한다.

## 실행

```powershell
./experiments/codex-astra-vs-6-luna/run-comparison.ps1 -RunId <run-id> -Order random
```

실행은 호스트 자원 경합을 피하려고 두 arm을 순차 실행한다. 순서는 `random`, `solo-first`, `multi-first` 중 선택하고 manifest에 남긴다. `TimeoutMinutes`는 각 arm 전체의 상한이며 기본값은 60분이다. 각 모델 실행의 JSONL 이벤트, stderr, 최종 답변, 세션 ID, 경과 시간, 모델명과 종료 코드를 `steps/` 아래에 따로 보관한다.

실행 후 두 worktree에서 공통 검증을 같은 순서로 실행하고 [평가표](RUBRIC.md)를 작성한다. 전체 로컬 검증은 시간이 걸리므로 모델 실행과 분리한다.

```powershell
./experiments/codex-astra-vs-6-luna/evaluate.ps1 -RunId <run-id>
./experiments/codex-astra-vs-6-luna/evaluate.ps1 -RunId <run-id> -Full
./experiments/codex-astra-vs-6-luna/evaluate.ps1 -RunId <run-id> -SoloQualityScore 82 -MultiQualityScore 91
```

`-Full`은 각 arm에서 전용 Docker 검증 스택을 순차 실행한다. 개인 `brainnet-local`은 사용하지 않는다. 한 번의 결과는 탐색치로 보고, 실제 선택에는 순서를 번갈아 3회 이상 실행한 중앙값과 품질 최악값을 사용한다.

## API 환산 비용

평가는 총토큰만 비교하지 않는다. `api-pricing.json`에 고정한 [OpenAI Standard API 가격](https://developers.openai.com/api/docs/pricing)을 사용해 각 단계와 모델별 USD 환산 비용을 계산한다.

- Astra: 1M 토큰당 입력 `$10`, 캐시 입력 `$1`, 캐시 쓰기 `$12.50`, 출력 `$50`
- Luna: 1M 토큰당 입력 `$0.10`, 캐시 입력 `$0.01`, 캐시 쓰기 `$0.125`, 출력 `$0.50`
- 기본값은 입력 컨텍스트 272K 이하 Standard 요율
- 모든 호출이 장문 컨텍스트였다고 가정한 민감도 비용도 함께 기록
- 추론 토큰은 출력 토큰에 포함되므로 이중 과금하지 않음

각 arm의 `api-cost.json`에는 단계별·모델별 토큰과 비용이 남고, `summary.json`에는 총 API 환산 비용, Astra 비용, Luna 비용, 품질 1점당 비용이 들어간다. 이것은 ChatGPT 로그인으로 실행한 Codex의 실제 청구액이 아니라 동일 토큰을 API Standard 요율로 실행했다고 가정한 비교 지표다. 도구별 별도 요금, 지역 가산, Fast mode 가산은 포함하지 않는다.

이 하네스는 브랜치를 자동 병합·푸시·삭제하지 않는다. 실험 결과와 worktree는 `.tools/` 아래에 있어 Git에 포함되지 않는다.
