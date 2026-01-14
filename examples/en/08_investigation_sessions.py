#!/usr/bin/env python3
"""
Example: Investigation Sessions with History and Reports

Demonstrates how to track multi-step investigations, undo/redo operations,
save/resume sessions, and generate professional reports.
"""

import logler.investigate as investigate

print("=" * 70)
print("Investigation Session Demo")
print("=" * 70)

log_file = "examples/logs/production_incident.log"

print("\n📝 Starting a new investigation session")
print("-" * 70)

# Create a session to track everything
session = investigate.InvestigationSession(files=[log_file], name="production_incident_2024_01_15")

print(f"Session name: {session.name}")
print(f"Files: {session.files}")

print("\n🔍 Step 1: Search for errors (tracked automatically)")
errors = session.search(level="ERROR", output_format="summary")
print(f"Found {errors['total_matches']} errors")

print("\n🔍 Step 2: Find patterns (tracked automatically)")
patterns = session.find_patterns(min_occurrences=2)
print(f"Found {len(patterns.get('patterns', []))} patterns")

print("\n🔍 Step 3: Add investigation notes")
session.add_note("Database connection pool appears to be exhausted based on error messages")

print("\n📋 View investigation history")
print("-" * 70)
history = session.get_history()
for i, entry in enumerate(history, 1):
    print(f"\n{i}. {entry['description']}")
    print(f"   Time: {entry['timestamp']}")
    print(f"   Operation: {entry['operation']}")
    if entry.get("result_summary"):
        for key, value in entry["result_summary"].items():
            print(f"   {key}: {value}")

print("\n⏮️  Undo last operation")
session.undo()
print(f"Current focus: {session.get_current_focus()['description']}")

print("\n⏭️  Redo operation")
session.redo()
print(f"Current focus: {session.get_current_focus()['description']}")

print("\n📄 Generate investigation report (Markdown)")
print("-" * 70)
report = session.generate_report(format="markdown")
print(report[:500] + "...\n[Report truncated for display]")

print("\n💾 Save session for later")
session.save("investigation_session.json")
print("Saved to: investigation_session.json")

print("\n📂 Resume session later")
resumed_session = investigate.InvestigationSession.load("investigation_session.json")
print(f"Resumed session: {resumed_session.name}")
print(f"Steps in history: {len(resumed_session.history)}")

print("\n📊 Get human-readable summary")
print("-" * 70)
print(session.get_summary())

print("\n" + "=" * 70)
print("Session features:")
print("✓ Track all investigation steps automatically")
print("✓ Undo/redo operations")
print("✓ Add notes and context")
print("✓ Save/resume investigations")
print("✓ Generate professional reports (Markdown/Text/JSON)")
print("✓ Review history to see what you've done")
print("=" * 70)
