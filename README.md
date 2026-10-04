# RunCoach

A running-first AI coach on Garmin data, with a deliberately small UI:
**Calendar · Chat · Diet · Profile**.

Ask the coach for a plan in chat; it proposes one (built by deterministic Python, named
and explained by the model); accept it and the calendar fills with structured workouts.
Every workout has a **Guide**, every synced run a **Review**, and the Diet tab sizes your
calories, carbs and run fueling to the day's training.

> **Python calculates. The model interprets.**

## Documents

- [CONTEXT.md](CONTEXT.md) — what this is, where it came from, decisions.
- [docs/SPEC.md](docs/SPEC.md) — screens, data model, calculators, API contract, milestones.

## Running it

```bash
docker compose up -d
```

Frontend http://localhost:5174 · API http://localhost:8001/api/health/ · admin `/admin`.

Ports are offset from MyRunAnalizer (5173/8000/5433/6380) so both can run side by side.
