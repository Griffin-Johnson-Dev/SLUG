# SLUG 1.0 Whitespace Invariance and Compound-Punctuation Compatibility

Status: **Language-contract clarification and compiler conformance requirement**

SLUG 1.0 intentionally makes ordinary whitespace outside strings/comments non-semantic at grammar boundaries. The 1.0.0 compiler already honored this for atomic lowercase/uppercase name characters, which is why forms such as `ci` and `c i` can resolve to the same builtin in context. It did **not** honor the rule for several structural/comparison composites: for example `:=` was accepted while `: =` could be tokenized as separate punctuation and then rejected. Compiler 1.0.1 repairs that implementation mismatch without changing language version 1.0.

## Whitespace-transparent composites

The following frozen structural/comparison spellings may contain spaces, tabs, or logical newlines between their characters:

```text
<:.   ::=   !==   ===   <:   :=   ==   !=   <=   >=
```

Examples:

```slug
n:=ci'name? '
n : = c i 'name? '
n
:
=
c
i
'name? '
```

Those forms parse equivalently. The same rule applies to the other whitespace-transparent composites above in grammar positions where they are valid.

## Compatibility-sensitive executable compounds

SLUG 1.0 also has executable compound punctuation:

```text
++   --   ^^   ~-   ~~   //
```

These require special care. Their component punctuation can itself form meaningful pre-existing token sequences. For example, two separated `/` tokens can be two RPN division operators, and two separated `+` tokens can be two RPN addition operators. A patch compiler must not greedily turn every separated pair into a compound token and thereby change an already-valid 1.0.0 program.

Therefore exact contiguous spellings retain their frozen compound-token identity, while separated component punctuation retains its existing tokenization unless a higher grammar layer can accept an equivalent spelling without reinterpreting a valid program. This is the compatibility boundary around SLUG's broader whitespace-invariance rule.

## What the implementation must not do

The compiler must **not** implement whitespace openness by deleting whitespace from the source string before lexing. That would destroy lexical information. A line comment must still end at its physical newline; following code must not be concatenated onto the comment line. String contents likewise remain exact source data subject only to normal string escape/interpolation rules, and block-comment boundaries remain intact.

Compiler 1.0.1 therefore performs whitespace-aware recognition only while matching the safe structural/comparison composite set. Comments are barriers to one composite token, and the token span records the complete original source range including intervening whitespace. Exact executable compound tokens remain exact.

## Regression strategy

`tests/run_v1_whitespace_invariance.py` is both a metamorphic and compatibility gate. It:

- inserts spaces, tabs, and newlines inside whitespace-transparent structural/comparison punctuation and requires the same semantic AST;
- checks the exact public bug report (`n:=ci...` versus `n : = c i...`);
- verifies strings are not rewritten and line comments do not swallow following code;
- verifies pre-existing separated executable punctuation keeps its tokenization;
- verifies exact contiguous executable compound tokens remain available;
- exercises native `slug check`, formatter, crusher, and re-check behavior when a native candidate is supplied.

The lexer/program differential corpora also contain direct spaced and multi-line spellings so the reference and self-hosted frontends must agree.

## Editor behavior

SLUG Lang DevKit 1.0.2 updates the TextMate grammar so same-line spaced builtins/keywords/classes and whitespace-transparent punctuation such as `c i`, `: =`, and `= =` receive the same broad syntax scopes as their compact forms. It deliberately **does not** color `+ +`, `- -`, `^ ^`, `~ -`, `~ ~`, or `/ /` as the corresponding contiguous compound operator. TextMate coloring remains a lexical approximation; semantic validity and diagnostics continue to come from the native SLUG compiler/LSP.
