# Security

ResolveLab's services are synthetic sandboxes: the CaseDesk HTTP service binds to 127.0.0.1 on
a random port for one episode, and the workbench (`resolvelab serve`) has no authentication
and binds to 127.0.0.1. Do not expose either to a network.

Please report a vulnerability privately through
[GitHub security advisories](https://github.com/Ta0p1/ResolveLab/security/advisories/new)
rather than a public issue. Useful reports include:

- a way for an episode, a model output or a ticket's text to reach outside the sandbox
  (files, network, other processes);
- a model provider that could leak an API key into a report, a trace or a log;
- a way for a policy to read hidden episode state (fault flags, expected records) that the
  grader relies on.

A policy that games the grader is not a security issue; open a "Grader or result concern"
issue instead.
