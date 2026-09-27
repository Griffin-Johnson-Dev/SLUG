# SLUG (Symbolic Low-Overhead Unified Grammar)

**SLUG** is a compact, compiled programming language built around dense syntax, deterministic ambiguity resolution, RPN arithmetic, explicit module identities, and a self-hosted native compiler.

**Language contract:** `1.0`  
**Compiler:** `1.0.2`  
**CLI contract:** `1`  
**VS Code DevKit:** `1.0.3`  
**License:** Apache-2.0

SLUG's maintained compiler is written in SLUG and bootstrapped through a canonical generated-C seed.

SLUG V1 currently targets **C11** as its native backend. The installed `slug` compiler itself does not require Python, but `slug build` and `slug run` require a working host C compiler to produce native executables.

## Platform support

| Platform | SLUG 1.0.2 status |
| --- | --- |
| x86-64 Windows 10/11 | **Certified** — LLVM Clang / clang-cl |
| x86-64 Linux | **Certified** — GCC and Clang |
| macOS | **Experimental** — portability path available, not release-certified |

Windows and Linux are the officially certified SLUG 1.0.2 platforms.

---

# Installation

For a normal SLUG setup you need:

1. **SLUG compiler 1.0.2**
2. **A C11 compiler** for `slug build` and `slug run`
3. **Python 3.11+** to construct the installed SLUG tree from the release archive
4. **SLUG Lang DevKit** for VS Code, if editor integration is wanted

A separate Node.js installation is **not required for normal VS Code usage**. Node.js 18+ is needed only when running the standalone `slug-lsp` JavaScript launcher outside VS Code.

> [!IMPORTANT]
> Download the explicit release asset:
>
> `SLUG-1.0.2-source.zip`
>
> Do **not** use GitHub's automatically generated **Source code (zip)** or **Source code (tar.gz)** archives when reproducing the certified 1.0.2 release. The named SLUG archive is the certified release artifact.

---

## Windows 10/11

SLUG 1.0.2 is certified on x86-64 Windows using LLVM/Clang.

### 1. Install Python

Install Python 3.11 or newer.

One Windows package-manager route is:

```powershell
winget install 9NQ7512CXL7T -e --accept-package-agreements --accept-source-agreements
```

Open a new PowerShell window and verify:

```powershell
python --version
```

### 2. Install the Windows C/C++ toolchain

Install Visual Studio 2022 Build Tools:

```powershell
winget install --id Microsoft.VisualStudio.2022.BuildTools -e
```

In the Visual Studio Installer, select:

- **Desktop development with C++**
- a current **Windows 10/11 SDK**

Then install LLVM:

```powershell
winget install --id LLVM.LLVM -e
```

Open a fresh PowerShell window and verify:

```powershell
clang-cl --version
clang --version
```

### 3. Install SLUG

Download and extract:

```text
SLUG-1.0.2-source.zip
```

Open PowerShell inside the extracted `SLUG-1.0.2` directory and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

The default installation directory is:

```text
%LOCALAPPDATA%\Programs\SLUG
```

with the compiler at:

```text
%LOCALAPPDATA%\Programs\SLUG\bin\slug.exe
```

### 4. Add SLUG to PATH

The installer intentionally does not silently modify your permanent `PATH`.

Add this directory to your **user Path**:

```text
%LOCALAPPDATA%\Programs\SLUG\bin
```

On Windows:

1. Search **Edit environment variables for your account**.
2. Select **Path** → **Edit**.
3. Click **New**.
4. Add the path above.
5. Save and open a new terminal.

Verify the installation:

```powershell
slug --version
slug --language-version
```

Expected:

```text
1.0.2
1.0
```

---

## Linux

SLUG 1.0.2 is certified on x86-64 Linux with both GCC and Clang.

The following commands use Debian/Ubuntu package names. Other distributions should install the equivalent packages using their package manager.

### 1. Install prerequisites

```sh
sudo apt update
sudo apt install -y build-essential python3 unzip
```

Verify:

```sh
python3 --version
cc --version
```

Python must be **3.11 or newer**.

Clang may optionally be installed with:

```sh
sudo apt install -y clang
```

### 2. Install SLUG

Download:

```text
SLUG-1.0.2-source.zip
```

Then:

```sh
unzip SLUG-1.0.2-source.zip
cd SLUG-1.0.2

chmod +x scripts/install.sh
./scripts/install.sh
```

The default installation prefix is:

```text
$HOME/.local
```

and the compiler is normally installed at:

```text
$HOME/.local/bin/slug
```

To explicitly build the installed compiler using Clang:

```sh
CC=clang ./scripts/install.sh
```

### 3. Add SLUG to PATH

For the current shell:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Verify:

```sh
slug --version
slug --language-version
```

Expected:

```text
1.0.2
1.0
```

To make the change permanent, add:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

to your shell startup file, commonly:

```text
~/.bashrc
```

or:

```text
~/.zshrc
```

---

## macOS

> [!WARNING]
> macOS is **not a certified SLUG 1.0.2 release platform**.
>
> The installation path below is provided as an experimental portability path rather than an official platform-support claim.

### 1. Install Apple's command-line developer tools

```sh
xcode-select --install
```

Verify:

```sh
clang --version
```

### 2. Install Python 3.11+

Install a current Python release, or use Homebrew:

```sh
brew install python
```

Verify:

```sh
python3 --version
```

### 3. Install SLUG

Download and extract:

```text
SLUG-1.0.2-source.zip
```

Open Terminal in the extracted directory and run:

```sh
chmod +x scripts/install.sh
CC=clang ./scripts/install.sh
```

Add the default installation directory to the current shell:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Verify:

```sh
slug --version
slug --language-version
```

Expected, if the portability path succeeds:

```text
1.0.2
1.0
```

For Zsh, the PATH export can be added permanently to:

```text
~/.zshrc
```

Because macOS has not completed SLUG 1.0.2 release certification, failures should be reported with the macOS version, architecture, Clang version, and resulting error.

---

# VS Code support

The official VS Code extension is:

**SLUG Lang DevKit**  
Publisher: `griffinjohnson`

Install it from the VS Code Extensions view by searching for:

```text
SLUG Lang DevKit
```

The extension provides:

- SLUG syntax highlighting
- native-backed diagnostics
- formatting
- project discovery
- relative-import resolution
- `@dep/*` dependency resolution
- native failure locations and source ranges

The client is intentionally thin: language behavior remains backed by the installed SLUG compiler rather than being independently reimplemented in the extension.

The extension normally discovers `slug` / `slug.exe` through `PATH`.

If it cannot, set:

```text
slug.compilerPath
```

to the installed compiler manually.

### Offline installation

The release also provides:

```text
slug-lang-devkit-1.0.3.vsix
```

In VS Code:

**Extensions → `...` → Install from VSIX...**

and select the file.

---

# Your first SLUG program

Create a file named:

```text
hello.slg
```

with:

```slug
co['Hello, SLUG!']
```

## Check the program

```sh
slug check hello.slg
```

A successful check is silent by default.

## Run the program

```sh
slug run hello.slg
```

Output:

```text
Hello, SLUG!
```

## Build a native executable

```sh
slug build hello.slg
```

Default output:

```text
Windows: hello.exe
Linux:   hello
macOS:   hello
```

Run it directly:

```powershell
# Windows
.\hello.exe
```

```sh
# Linux/macOS
./hello
```

---

# Core CLI

### Check source

```sh
slug check <file.slg>
```

Lexes, parses, resolves imports, constructs the module graph, and performs semantic validation without creating an executable.

### Run source

```sh
slug run <file.slg>
```

Checks the program, compiles it through the host C toolchain, and executes the resulting native program.

### Build an executable

```sh
slug build <file.slg>
```

Useful build options include:

```text
-o <output>       choose the output path
--cc <compiler>   choose the host C compiler
--keep-c          preserve generated C
```

### Version information

```sh
slug --version
slug --language-version
```

For SLUG 1.0.2:

```text
1.0.2
1.0
```

See `docs/SLUG_PUBLIC_CLI_V1.md` for the complete CLI contract.

---

# Projects

SLUG projects may use a `slug.json` manifest defining an entry file and deterministic local dependency roots.

V1 does **not** include a network package registry or automatic Internet dependency resolution.

See:

```text
docs/SLUG_V1_INSTALL_AND_PROJECT_LAYOUT.md
```

for project and installation layout details.

---

# Examples

User-facing SLUG 1.0 examples are available in:

```text
examples/
```

Start with:

```text
examples/README.md
```

The examples directory contains only current V1 syntax.

Historical and recovery material elsewhere in the repository may contain obsolete pre-1.0 syntax and should not be treated as language documentation.

---

# Repository layout

```text
compiler/
```

Maintained self-hosted SLUG compiler and native runtime.

```text
bootstrap/
```

Canonical generated-C bootstrap seed. This crosses the bootstrap boundary but is not the language specification.

```text
docs/
```

Language, compiler, CLI, platform, project, and release documentation.

Important documents include:

- `SLUG_V1_SPECIFICATION.md` — normative language semantics
- `SLUG_PUBLIC_CLI_V1.md` — public CLI contract
- `SLUG_V1_COMPILER_ARCHITECTURE.md` — compiler/runtime/tooling architecture
- `SLUG_V1_STANDARD_MODULES.md` — standard-module surface
- `SLUG_V1_SUPPORTED_PLATFORMS.md` — certified platform/toolchain matrix
- `SLUG_V1_INSTALL_AND_PROJECT_LAYOUT.md` — installation and project layout
- `SLUG_V1_RELEASE_PROCESS.md` — reproducible release procedure

```text
tooling/lsp/
tooling/vscode/
```

Native-backed language-server and VS Code integration.

```text
tests/
```

Conformance, bootstrap, linkage, tooling, hardening, and adversarial release gates.

```text
historical/
recovery_authority/
```

Development and recovery history. These directories are non-normative.

---

# Language status

The **SLUG V1 language design is frozen**.

Compiler `1.0.2` implements language contract `1.0` and CLI contract `1`.

SLUG 1.0.2 adds the backward-compatible explicit:

```slug
@std/list
```

standard module permitted by the V1 compatibility rules.

It retains the 1.0.1 whitespace-invariance repair, self-hosted native compiler, and failure-only native provenance for lexical, structural, parse, and semantic diagnostics.

The nine frozen implicit root builtins remain unchanged.

Existing valid SLUG 1.0 programs retain their meaning.

---

# Self-hosting and bootstrap

The maintained compiler is written in SLUG.

A checked-in generated-C seed in `bootstrap/` crosses the initial bootstrap boundary. The release process then rebuilds the compiler through successive self-host generations and verifies fixed-point convergence.

For direct bootstrap experimentation, a C11 compiler may be used manually.

On Linux with GCC:

```sh
gcc -std=c11 -O2 bootstrap/slug_seed.c -lm -o slug
./slug --version
./slug --language-version
```

This is primarily a bootstrap/developer path.

Normal users should use the platform installation instructions above.

---

# Security

`slug run` is **not a sandbox**.

It compiles and executes the requested program using the operating-system permissions of the invoking user.

Do not use it to execute untrusted SLUG source.

See:

```text
SECURITY.md
```

for the security policy.

---

# Documentation authority

If historical material, recovery checkpoints, examples, or implementation notes disagree with current V1 behavior, use the following authority order:

1. `docs/SLUG_V1_SPECIFICATION.md`
2. `docs/SLUG_PUBLIC_CLI_V1.md`
3. `docs/SLUG_V1_STANDARD_MODULES.md`
4. audited V1 conformance tests
5. `docs/SLUG_V1_STABILITY_AND_AUTHORITY.md`

Recovery checkpoints and pre-V1 material exist for provenance and historical purposes only.

---

# Release status

SLUG `1.0.0` is the immutable first stable release.

SLUG `1.0.1` is the whitespace-conformance patch release.

SLUG `1.0.2` is the current certified patch release for language contract `1.0`. It adds the explicit `@std/list` capability module without changing root syntax or the public CLI contract.

SLUG 1.0.2 is release-certified on:

- x86-64 Windows with LLVM Clang / clang-cl
- x86-64 Linux with GCC
- x86-64 Linux with Clang

macOS remains an experimental portability path until a real macOS certification is completed.
