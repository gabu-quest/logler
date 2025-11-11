#!/usr/bin/env python3
"""
Example: Complete LLM Investigation Workflow

Demonstrates a full investigation workflow combining all LLM features:
auto insights, token efficiency, sessions, sampling, and explanations.
"""

import logler.investigate as investigate

print("=" * 70)
print("Complete LLM Investigation Workflow")
print("=" * 70)

log_file = "examples/logs/production_incident.log"

# Phase 1: Quick triage with auto insights
print("\n🚀 PHASE 1: Quick Triage (token-efficient)")
print("-" * 70)

result = investigate.analyze_with_insights(
    files=[log_file],
    auto_investigate=True
)

print(f"Error rate: {result['overview']['error_rate']:.1%}")
print(f"Insights found: {len(result['insights'])}")

if result['insights']:
    top_insight = result['insights'][0]
    print(f"\nTop insight: [{top_insight['severity'].upper()}] {top_insight['description']}")
    print(f"Suggestion: {top_insight['suggestion']}")

# Phase 2: Start investigation session
print("\n📝 PHASE 2: Detailed Investigation (with session tracking)")
print("-" * 70)

session = investigate.InvestigationSession(
    files=[log_file],
    name="incident_investigation"
)

# Step 1: Get representative sample (token-efficient)
print("\nStep 1: Get representative sample")
sample = investigate.smart_sample(
    files=[log_file],
    strategy="errors_focused",
    sample_size=10
)
print(f"  Sampled {sample['sample_size']} from {sample['total_population']} entries")
session.add_note(f"Analyzed sample of {sample['sample_size']} entries")

# Step 2: Search for errors (summary format)
print("\nStep 2: Search for errors (token-efficient)")
errors = session.search(level="ERROR", output_format="summary")
print(f"  Found {errors['total_matches']} errors")
print(f"  Unique messages: {errors['unique_messages']}")

# Step 3: Find patterns
print("\nStep 3: Find error patterns")
patterns = session.find_patterns(min_occurrences=2)
print(f"  Found {len(patterns.get('patterns', []))} patterns")

if patterns.get('patterns'):
    top_pattern = patterns['patterns'][0]
    print(f"  Top pattern: {top_pattern.get('pattern', '')[:60]}...")
    print(f"  Occurrences: {top_pattern.get('occurrences', 0)}")

    # Phase 3: Explain the top error
    print("\n🤔 PHASE 3: Understand the Error")
    print("-" * 70)

    if top_pattern.get('examples'):
        example = top_pattern['examples'][0]
        explanation = investigate.explain(
            entry=example,
            context="production"
        )
        print(explanation[:400] + "...\n[Explanation truncated]")
        session.add_note("Identified root cause: connection pool exhaustion")

# Phase 4: Generate report
print("\n📄 PHASE 4: Generate Investigation Report")
print("-" * 70)

print(session.get_summary())

# Save the report
report = session.generate_report(format="markdown")
with open("investigation_report.md", "w") as f:
    f.write(report)
print("\n✓ Report saved to: investigation_report.md")

# Save session
session.save("investigation_session.json")
print("✓ Session saved to: investigation_session.json")

print("\n" + "=" * 70)
print("Complete Workflow Summary:")
print("=" * 70)
print("\n1. Quick Triage:")
print("   ✓ analyze_with_insights() - One function for automatic analysis")
print("   ✓ Token-efficient summary output")
print("   ✓ Immediate actionable insights")

print("\n2. Detailed Investigation:")
print("   ✓ InvestigationSession - Track all steps")
print("   ✓ smart_sample() - Representative sampling")
print("   ✓ search(output_format='summary') - Minimize tokens")
print("   ✓ find_patterns() - Detect systematic issues")

print("\n3. Root Cause Analysis:")
print("   ✓ explain() - Understand cryptic errors")
print("   ✓ Context-aware suggestions")
print("   ✓ Production-specific advice")

print("\n4. Documentation:")
print("   ✓ Auto-generated investigation report")
print("   ✓ Complete timeline with results")
print("   ✓ Save/resume capability")

print("\n💡 This workflow is optimized for LLMs:")
print("   • Minimizes token usage at every step")
print("   • Provides automatic insights and suggestions")
print("   • Tracks investigation history")
print("   • Generates professional reports")
print("   • Can be saved and resumed")

print("\n" + "=" * 70)
