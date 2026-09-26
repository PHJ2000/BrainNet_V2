# GPT-6 Astra 단독 vs Astra + Luna 6개 비교

동일한 BrainNet 기능 과제를 같은 커밋에서 두 독립 worktree로 실행하는 로컬 비교 하네스다.

- `solo`: GPT-6 Astra `max`, multi-agent 기능 비활성화
- `multi`: 역할이 분리된 GPT-6 Luna `max` 6개 + 최종 GPT-6 Astra `max` 통합
- 공통: 같은 `TASK.md`, workspace-write sandbox, 승인 없음, 커밋·푸시·개인 DB 변경 금지

[공식 모델 선택 문서](https://developers.openai.com/api/docs/guides/model-selection)는 Astra를 복잡한 종합 작업, Luna를 범위가 명확한 작업에 권장한다. [공식 멀티 에이전트 문서](https://developers.openai.com/api/docs/guides/responses-multi-agent)는 역할 분리가 유리하지만 토큰과 공유 상태 충돌 비용이 있다고 설명한다. 그래서 멀티 arm은 호스트 스크립트가 Luna 전문 세션을 `설계 → 데이터 → 백엔드 → 프런트 → 테스트 → 보안 검토` 순서로 정확히 6번 실행하고 Astra가 마지막에 통합한다. 내장 위임 성공 여부를 모델의 자기 보고에 맡기지 않는다.

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

실행은 호스트 자원 경합을 피하려고 두 arm을 순차 실행한다. 순서는 `random`, `solo-first`, `multi-first` 중 선택하고 manifest에 남긴다. `TimeoutMinutes`는 각 arm 전체의 상한이며 기본값은 60분이다. 각 모델 실행의 JSONL 이벤트, stderr, 최종 답변, 경과 시간, 모델명과 종료 코드를 `steps/` 아래에 따로 보관한다. 멀티 arm은 Luna 성공 실행이 정확히 6개가 아니면 실패한다.

실행 후 두 worktree에서 공통 검증을 같은 순서로 실행하고 [평가표](RUBRIC.md)를 작성한다. 전체 로컬 검증은 시간이 걸리므로 모델 실행과 분리한다.

```powershell
./experiments/codex-astra-vs-6-luna/evaluate.ps1 -RunId <run-id>
./experiments/codex-astra-vs-6-luna/evaluate.ps1 -RunId <run-id> -Full
```

`-Full`은 각 arm에서 전용 Docker 검증 스택을 순차 실행한다. 개인 `brainnet-local`은 사용하지 않는다. 한 번의 결과는 탐색치로 보고, 실제 선택에는 순서를 번갈아 3회 이상 실행한 중앙값과 품질 최악값을 사용한다.

JSONL의 토큰 수는 실행량 비교용이다. ChatGPT 로그인으로 실행하므로 이를 API 청구액으로 환산하지 않으며, 계정별 사용 한도와 실제 과금 여부도 이 하네스가 판단하지 않는다.

이 하네스는 브랜치를 자동 병합·푸시·삭제하지 않는다. 실험 결과와 worktree는 `.tools/` 아래에 있어 Git에 포함되지 않는다.
