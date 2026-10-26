# Architecture

The sealed Agent owns customer intent, business decisions, orchestration, and
business acceptance. The business service owns third-party API adapters,
provider credentials, budgets, and persistent server-side business state. The
local capability performs bounded device-side I/O or compute and returns
technical facts. DClaw provides identity, capability authorization, cards,
trace propagation, the local gateway, and the generic Runner.
