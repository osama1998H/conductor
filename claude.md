# CLAUDE.md — Clean Code Rules

Use this file as the default coding standard for this repository.  
When in doubt, optimize for readability, change safety, and low cognitive load.

## Core principles

- Prefer code that is easy for humans to read, understand, and modify.
- Keep the design simple; do not introduce abstraction unless it clearly reduces complexity.
- Remove duplication aggressively.
- Make intent obvious in the code itself.
- Leave every file, function, and class cleaner than you found it.

## Naming

- Use intention-revealing names.
- Choose names that explain purpose, not implementation details.
- Avoid abbreviations unless they are universally understood in the codebase.
- Avoid names that differ by only a letter or two.
- Keep names pronounceable and searchable.
- Use domain vocabulary consistently.
- Do not encode types, prefixes, or implementation details in names unless they add real value.
- Prefer nouns for classes and verbs for functions.
- Prefer precise names over short clever ones.
- Use one word per concept and one concept per word.

## Functions

- Keep functions small.
- Each function should do one thing and do it well.
- A function should have a single level of abstraction.
- Read code top to bottom like a story.
- Minimize arguments; 0–2 is ideal, 3 is a warning sign, more than 3 should be exceptional.
- Avoid output parameters.
- Prefer pure functions when possible.
- Avoid flag arguments.
- Avoid side effects unless they are the explicit purpose of the function.
- Use descriptive names for functions.
- Prefer command/query separation: a function should either do work or return information, not both.
- Keep control flow straightforward and shallow.
- Extract nested logic into well-named helper functions.
- Avoid switch or if chains that repeat the same pattern; replace them with polymorphism, maps, or strategy objects when appropriate.

## Comments

- Write comments only when they add information that the code cannot express itself.
- Do not use comments to explain bad names or bad structure; fix the code instead.
- Avoid redundant, stale, or misleading comments.
- Avoid commented-out code.
- Use comments for legal requirements, non-obvious intent, public API constraints, and unusually tricky tradeoffs.
- Prefer self-explanatory code over comment-heavy code.

## Formatting

- Keep formatting consistent across the repository.
- Use vertical whitespace to separate concepts.
- Keep related code close together.
- Use blank lines to show logical boundaries.
- Keep line length reasonable for readability.
- Align formatting with the team’s conventions and automated formatters.
- Make the visual structure of the file communicate the structure of the design.

## Objects and data structures

- Prefer objects when behavior should stay close to data.
- Prefer data structures when you want to add new functions without changing existing types.
- Prefer encapsulation over exposing internals.
- Do not violate the Law of Demeter; talk to friends, not strangers.
- Hide implementation details behind behavior-focused methods.
- Avoid train-wreck navigation chains.
- Choose the right abstraction for the job; “everything is an object” is not a rule.

## Error handling

- Use exceptions rather than return codes when the language and architecture support them.
- Keep error handling separate from the happy path.
- Handle errors at the correct level of abstraction.
- Do not let error-handling logic obscure business logic.
- Fail fast on invalid inputs.
- Validate assumptions at boundaries.
- Throw meaningful errors with enough context to diagnose the failure.
- Prefer one clear strategy for error propagation in each layer.
- Do not swallow errors silently.

## Tests

- Test code must be as clean as production code.
- Tests should be readable, focused, and easy to maintain.
- Keep test setup minimal and expressive.
- Use descriptive test names that explain behavior.
- Test one behavior per test when practical.
- Keep tests deterministic.
- Cover boundary conditions, error paths, and important edge cases.
- Prefer automated tests over manual verification.
- Refactor dirty tests immediately; dirty tests are technical debt.
- Tests should protect design, not just validate outputs.

## Classes

- Keep classes small.
- A class should have one reason to change.
- Prefer cohesion over convenience.
- Put related behavior together.
- Expose the smallest useful surface area.
- Avoid “god classes” and classes that mix too many responsibilities.
- Keep constructors simple.
- Prefer composition over inheritance when it reduces coupling.
- Classes should read like focused parts of a system, not mini-applications.

## Concurrency

- Treat concurrency as a design constraint, not an afterthought.
- Keep shared mutable state to a minimum.
- Prefer immutability where possible.
- Separate what must happen from when it happens.
- Keep concurrent code as simple and isolated as possible.
- Make thread-safety assumptions explicit.
- Test concurrent behavior carefully.

## Smells to eliminate

- Duplication.
- Long functions.
- Large classes.
- Deep nesting.
- Mixed abstraction levels.
- Hard-coded magic values.
- Poorly chosen names.
- Excessive comments.
- Hidden side effects.
- Tight coupling.
- Premature generalization.
- Data clumps.
- Feature envy.
- Dead code.
- Inconsistent formatting.
- Dirty tests.

## Practical decision rules

- If the code is hard to explain, simplify it.
- If a name needs a comment, rename it.
- If a function needs a paragraph of explanation, split it.
- If a class keeps growing, split responsibilities.
- If a change touches too many files, revisit the boundaries.
- If a test is hard to read, rewrite it.
- If a design choice only helps today’s case, avoid locking it in too early.
- If two things change for different reasons, separate them.

## Review checklist

Before merging, verify:

- Names reveal intent.
- Functions are short and single-purpose.
- Tests are clear and sufficient.
- Comments are necessary and accurate.
- Formatting is consistent.
- Error handling does not obscure logic.
- Classes are cohesive and small.
- The code avoids unnecessary duplication.
- The design is easy to extend without large rewrites.
- The final result is simpler than the version that came before it.
