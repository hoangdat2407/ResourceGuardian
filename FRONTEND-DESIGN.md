# Frontend design — 2026-10-11

Apply the provided `skill.md`. Audience: Vietnamese AWS newcomers connecting a read role, then reviewing evidence before taking action.

## Plan and critique before implementation

Palette: ink #193849, sea #126782, mist #eef4f6, paper #ffffff, amber #995c12, error #a52e38. Typography: locally available Segoe UI for Vietnamese interface text; Georgia only for the welcome statement, with Vietnamese fallback. Body 15px, labels 14px, section 20px, page 32px. Left aligned; comfortable line lengths.

Initial idea: four equal KPI cards above a card grid. Rejected because this repeats a generic SaaS layout and makes unscanned accounts look like measured data. Revised: one continuous inventory strip, a prominent actionable scan-state panel, then evidence rows. The connection workflow is the distinctive element: a numbered procedural rail paired with a practical parameter sheet, followed by the connection form and first-scan instructions. Numbers represent actual sequential actions.

```text
navigation | page title                      scan
           | current state + next action
           | inventory strip
           | account scope | scan by region
           | evidence table

connection | 1. download and create stack | copy parameters
           | 2. Role ARN and regions
           | 3. first scan and interpretation
```

On mobile: compact two-column navigation, single-column steps, evidence rows become labeled blocks. Use visible focus, native controls, 44px targets, no ambient animation, reduced-motion support. No gradients or decorative statistics; amber marks review candidates, blue denotes observation, red denotes failures. Never use zero to mean unknown. Partial results must describe scope and truncation. Keep authentication, API payloads, rules and infrastructure unchanged.

## Verification

Use the existing local demo smoke test plus isolated API fixtures for new-user, failed connection, partial/empty/queued/running/failed/timed-out scans, unavailable SES, API outage and responsive layouts. Fixtures stay in tests. Inspect screenshots before delivery. AWS deployment is a separate gate requiring available AWS MCP, identity, stack Outputs, online backup and preserved production config.

CloudFormation console wording was checked against the [official create-stack guide](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stack.html) and [IAM capabilities guidance](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/control-access-with-iam.html). No IAM policy was changed.
