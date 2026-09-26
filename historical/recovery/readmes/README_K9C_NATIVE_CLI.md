# K9C Native Public CLI

K9C is the first clean bootstrap state whose **self-hosted native SLUG compiler binary** implements Public CLI Contract v1 directly.

Public commands implemented natively:

- `slug check`
- `slug build`
- `slug run`
- `slug fmt`
- `slug crush`
- `slug expand`
- `slug --version`
- `slug --language-version`
- `slug --help` / `slug help`

The CLI includes compiler-owned exit classes, schema-1 NDJSON diagnostics, build/run argument handling, overwrite safety, and token-stream guarded source transforms. It does not delegate these public behaviors to the Python reference compiler.

The K9C backend also repairs exception-frame unwinding for nonlocal control flow through `try/catch/finally`, ensuring generated `return`, `break`, and `continue` paths restore exception frames and execute required `finally` bodies.

Run the clean bootstrap proof with:

```sh
./bootstrap/verify_bootstrap.sh
```
