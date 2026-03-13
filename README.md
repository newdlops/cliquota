# cliquota

`tmux` 안에서 `Gemini`와 `Codex`를 함께 쓸 때 필요한 상태 표시, 세션 분리, 마우스 스크롤백, 드래그 복사 동작을 한 번에 설치하는 패키지입니다.

이 패키지는 현재 기기에서 검증된 설정을 다른 기기에도 그대로 옮길 수 있도록 만든 배포용 설치본입니다.

## 이 패키지가 해결하는 문제

- `tmux` 상태 줄에서 `Gemini`와 `Codex`의 정보를 표시합니다.
- 여러 pane 또는 여러 터미널 창에서 실행된 세션이 서로 섞이지 않도록 pane 기준으로 상태를 분리합니다.
- `Gemini`를 새 터미널 창에서 실행할 때 기존 tmux 세션에 자동 재접속되지 않도록 별도 tmux 세션으로 띄웁니다.
- 마우스 휠 스크롤 시 셸 출력 스크롤백을 볼 수 있게 합니다.
- 마우스 드래그, 더블클릭, 트리플클릭으로 텍스트 선택과 복사를 사용할 수 있게 합니다.

## 설치되는 파일

설치 스크립트는 아래 파일을 사용자 홈 디렉터리 기준으로 배치합니다.

- `~/.gemini/tmux_status.py`
- `~/.codex/bin/codex-rate-limits`
- `~/.codex/bin/codex-status-pane`
- `~/.cliquota/tmux.conf`
- `~/.cliquota/gemini-wrapper.zsh`
- `~/.cliquota/bin/copy-text`

추가로 아래 두 설정 파일에는 관리 블록만 삽입합니다.

- `~/.tmux.conf`
- `~/.zshrc`

즉 기존 파일 전체를 덮어쓰지 않고, `cliquota`가 관리하는 블록만 추가하거나 갱신합니다.

## 설치 전 요구 사항

주의:
현재 이 패키지는 macOS 환경에서만 동작을 보장합니다. `pbcopy`, 현재 `tmux` 동작 검증, Gemini/Codex CLI 사용 패턴 모두 macOS 기준으로 맞춰져 있습니다. 특히 IntelliJ 터미널과 함께 쓸 때는 `tmux`가 outer terminal의 alternate screen을 정상적으로 사용할 수 있어야 하므로, 예전처럼 `smcup`/`rmcup`를 강제로 끄는 설정은 포함하지 않습니다.

다음 명령이 설치 대상 기기에 있어야 합니다.

- `tmux`
- `python3`
- `zsh`

클립보드 복사를 위해 아래 중 하나가 있으면 됩니다.

- macOS: `pbcopy`
- Wayland: `wl-copy`
- X11: `xclip` 또는 `xsel`
- Windows 계열 환경: `clip.exe`

다만 위 대체 클립보드 명령을 일부 지원하더라도, 실제 패키지 전체 동작은 macOS 외 환경에서 검증하지 않았습니다.

## 설치 방법

GitHub에서 받아 설치하는 방법은 두 가지가 있습니다.

### 1. `git clone`으로 내려받기

가장 권장하는 방식입니다.

```bash
cd ~/Desktop
git clone https://github.com/newdlops/cliquota.git
cd cliquota
./install.sh
```

### 2. GitHub ZIP으로 내려받기

GitHub 저장소 페이지에서 `Code` -> `Download ZIP`으로 압축 파일을 받은 뒤 적당한 위치에 풀고 설치합니다.

```bash
cd ~/Desktop/cliquota
./install.sh
```

이미 다른 기기에 `cliquota` 폴더를 직접 복사해 둔 상태여도 같은 방식으로 설치하면 됩니다.

```bash
cd ~/Desktop/cliquota
./install.sh
```

설치가 끝나면 다음 작업이 자동으로 수행됩니다.

1. 필요한 파일을 `~/.gemini`, `~/.codex/bin`, `~/.cliquota` 아래에 복사합니다.
2. `~/.tmux.conf`에 `~/.cliquota/tmux.conf`를 불러오는 관리 블록을 추가합니다.
3. `~/.zshrc`에 `~/.cliquota/gemini-wrapper.zsh`를 불러오는 관리 블록을 추가합니다.
4. 가능하면 현재 실행 중인 tmux에 설정을 다시 읽힙니다.
5. `zsh`와 Python 문법 검사를 수행합니다.

설치 후 새 터미널을 열거나 아래 명령을 실행하면 셸 설정이 즉시 반영됩니다.

```bash
source ~/.zshrc
```

## 설치 후 바뀌는 동작

### 1. tmux 상태 줄

오른쪽 상태 줄이 `~/.gemini/tmux_status.py`를 통해 현재 pane 기준 정보를 표시합니다.

- `Gemini`: 선택된 모델, 남은 사용량 백분율, 리셋까지 남은 시간
- `Codex`: 모델, 5시간 제한, 주간 제한, 컨텍스트 사용량

중요한 점은 이 정보가 이제 `pane_id`, `pane_pid`, `pane_tty`를 기준으로 계산된다는 것입니다. 그래서 여러 창에서 동시에 실행해도 다른 pane의 상태를 잘못 가져올 가능성이 줄어듭니다.

### 2. Gemini 실행 방식

`gemini` 명령은 `~/.cliquota/gemini-wrapper.zsh`를 통해 감싸집니다.

- 이미 tmux 안에 있으면: 현재 pane에서 그대로 `gemini`를 실행합니다.
- tmux 밖에서 실행하면: `gemini-<timestamp>-<pid>` 형식의 새 tmux 세션을 만들어 그 안에서 실행합니다.

이 설정 때문에 새 터미널 창에서 `gemini`를 실행해도 항상 같은 tmux 세션 `gemini`에 붙는 문제가 사라집니다.

### 3. 마우스 스크롤과 드래그 복사

`tmux` 마우스 설정은 다음 기준으로 동작합니다.

- 휠 업: 터미널 프로그램 자체 스크롤이 아니라 tmux scrollback 기준으로 위쪽 출력 보기
- 드래그: copy-mode에서 선택 시작
- 드래그 해제: 선택 내용을 클립보드로 복사하되 선택은 유지
- 더블클릭: 단어 복사
- 트리플클릭: 줄 전체 복사
- `Enter`: 현재 선택 영역 복사 후 copy-mode 종료

즉 마우스로 스크롤할 때 IntelliJ나 일반 터미널 앱의 바깥 스크롤백이 움직이는 것이 아니라, tmux 내부 scrollback이 움직이도록 사용하는 구성을 기본으로 합니다.

tmux 스크롤 상태에서 빠져나오려면 아래 방법을 사용하면 됩니다.

- `q`: copy-mode 종료
- `Enter`: 현재 선택 내용을 복사하고 종료
- 화면 맨 아래까지 내려간 뒤 추가 입력 수행: 일반 실행 화면으로 복귀

IntelliJ 터미널이나 일부 터미널 앱에서 바깥 스크롤과 tmux 스크롤이 충돌하면 `prefix + m`으로 tmux mouse mode를 끄고, 다시 tmux 기준 스크롤과 복사를 쓰고 싶을 때 같은 키로 다시 켤 수 있습니다.

다만 IntelliJ 터미널에서는 가능하면 IntelliJ 자체 스크롤보다 tmux 스크롤을 우선으로 쓰는 것을 권장합니다. 이 패키지도 그 사용 방식을 기준으로 맞춰져 있습니다. `mouse` 옵션은 tmux의 세션 옵션이므로, IntelliJ에서 붙은 세션에서만 `prefix + m`으로 조정할 수 있습니다.

또한 IntelliJ 터미널과의 충돌을 줄이기 위해 이 패키지는 `terminal-overrides ',*:smcup@:rmcup@'` 같은 설정을 기본 포함하지 않습니다. 그 설정은 outer terminal의 alternate screen까지 막아 IntelliJ 스크롤과 tmux 스크롤이 동시에 보이는 문제를 만들 수 있습니다.

IntelliJ에서 wheel 이벤트가 tmux로 제대로 들어오게 하려면 IntelliJ Terminal 설정의 `Mouse reporting`이 켜져 있어야 합니다. JetBrains 공식 문서:

- https://www.jetbrains.com/help/idea/settings-tools-terminal.html

추가로 IntelliJ 2025.2 이후에는 `Reworked 2025`가 기본 엔진일 수 있는데, tmux와의 호환성과 입력 전달을 우선하면 `Classic` 엔진을 권장합니다. JetBrains 공식 문서 기준으로 `Classic`은 JediTerm 기반의 표준 터미널이며, 사용자 입력이 underlying shell로 직접 전달됩니다.

- https://www.jetbrains.com/help/idea/terminal-emulator.html

클립보드 복사는 `~/.cliquota/bin/copy-text`가 담당하며, 시스템에 맞는 복사 명령을 자동으로 선택합니다.

## 백업과 복구

설치 스크립트가 건드리는 기존 파일은 모두 아래 경로에 백업됩니다.

```bash
~/.cliquota/backups/<timestamp>/
```

복구가 필요하면 해당 백업 디렉터리에서 원래 파일을 직접 되돌리면 됩니다.

대표적으로 백업되는 대상은 다음과 같습니다.

- 기존 `~/.tmux.conf`
- 기존 `~/.zshrc`
- 기존 `~/.gemini/tmux_status.py`
- 기존 `~/.codex/bin/codex-rate-limits`
- 기존 `~/.codex/bin/codex-status-pane`

## 업데이트 방법

설치 후 설정을 갱신하는 방법은 내려받은 방식에 따라 다릅니다.

### 1. GitHub에서 `git clone`으로 설치한 경우

저장소 디렉터리에서 최신 변경을 받은 뒤 설치 스크립트를 다시 실행합니다.

```bash
cd ~/Desktop/cliquota
git pull
./install.sh
```

### 2. ZIP으로 내려받아 설치한 경우

GitHub에서 최신 ZIP을 다시 받아 기존 폴더를 교체한 뒤 설치 스크립트를 다시 실행합니다.

```bash
cd ~/Desktop/cliquota
./install.sh
```

### 3. 로컬에서 직접 패키지 파일을 수정한 경우

이 패키지 내부 파일을 수정한 뒤 같은 기기에서 다시 설치하면 됩니다.

```bash
cd ~/Desktop/cliquota
./install.sh
```

같은 관리 블록을 다시 쓰는 방식이므로 중복으로 계속 쌓이지 않습니다.

## 제거 방법

완전 제거는 수동으로 하는 편이 안전합니다.

1. `~/.tmux.conf`에서 `cliquota tmux` 관리 블록을 삭제합니다.
2. `~/.zshrc`에서 `cliquota gemini` 관리 블록을 삭제합니다.
3. 필요하면 아래 파일을 삭제합니다.

- `~/.cliquota`
- `~/.gemini/tmux_status.py`
- `~/.codex/bin/codex-rate-limits`
- `~/.codex/bin/codex-status-pane`

그 다음 새 셸을 열고, tmux 안에서는 아래 명령으로 설정을 다시 읽히면 됩니다.

```bash
tmux source-file ~/.tmux.conf
```

## 패키지 구성

현재 폴더 구조는 대략 아래와 같습니다.

```text
cliquota/
├── install.sh
├── README.md
└── payload/
    ├── tmux.conf
    ├── gemini-wrapper.zsh
    ├── bin/
    │   └── copy-text
    ├── .gemini/
    │   └── tmux_status.py
    └── .codex/
        └── bin/
            ├── codex-rate-limits
            └── codex-status-pane
```

## 참고

- 현재 배포본은 macOS에서만 동작을 보장합니다.
- `tmux.conf`는 절대 경로 대신 `$HOME` 기준으로 작성되어 다른 사용자 계정에서도 그대로 설치할 수 있습니다.
- 설치 스크립트는 현재 tmux 세션이 있으면 자동으로 `source-file`을 시도합니다.
- 일부 TUI 프로그램은 자체 마우스 동작과 tmux copy-mode가 충돌할 수 있습니다. 이 패키지는 scrollback과 복사 편의성을 우선하도록 맞춰져 있습니다.
