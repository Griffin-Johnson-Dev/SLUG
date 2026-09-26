# Security

## `slug run` is not a sandbox

`slug run` compiles and executes SLUG code with the same operating-system permissions as the user who invoked the compiler. The SLUG compiler, runtime, LSP, and VS Code extension do not attempt to sandbox untrusted source.

Do not run, build, or open untrusted SLUG projects in an environment where compiler execution, project files, or native capabilities could cause unwanted effects. Standard modules such as filesystem, networking, process, graphics, audio, and device facilities are ordinary native capabilities subject to the host OS and the invoking user's permissions.

## Reporting a vulnerability

Report security defects through the repository's private security-advisory/reporting channel when available. If the distribution host does not expose one, contact the project maintainer privately rather than publishing exploit details before a fix can be prepared.

## Scope

Compiler crashes, memory-safety defects, incorrect path/project isolation, malformed-source denial of service, and editor/tooling paths that unexpectedly mutate source files are considered security-relevant defects. Language programs intentionally using documented native capabilities are not sandbox escapes because no sandbox is promised.
