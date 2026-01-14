#!/usr/bin/env python3
"""
Example: Explain Errors in Plain English

Demonstrates the explain() function that translates cryptic errors
into human-friendly explanations with common causes and next steps.
"""

import logler.investigate as investigate

print("=" * 70)
print("Explain Errors Demo - Cryptic errors made simple!")
print("=" * 70)

# Example 1: Connection pool exhausted
print("\n🔴 Error 1: Connection pool exhausted")
print("-" * 70)
explanation = investigate.explain(error_message="Connection pool exhausted", context="production")
print(explanation)

# Example 2: Timeout
print("\n\n🔴 Error 2: Database timeout")
print("-" * 70)
explanation = investigate.explain(
    error_message="Database query timed out after 30 seconds", context="production"
)
print(explanation)

# Example 3: Connection refused
print("\n\n🔴 Error 3: Connection refused")
print("-" * 70)
explanation = investigate.explain(
    error_message="Connection refused: http://api.service:8080", context="production"
)
print(explanation)

# Example 4: Out of memory
print("\n\n🔴 Error 4: Out of memory")
print("-" * 70)
explanation = investigate.explain(
    error_message="OutOfMemoryError: Java heap space", context="production"
)
print(explanation)

# Example 5: Null pointer
print("\n\n🔴 Error 5: Null reference")
print("-" * 70)
explanation = investigate.explain(
    error_message="NullPointerException at UserService.java:42", context="development"
)
print(explanation)

# Example 6: Permission denied
print("\n\n🔴 Error 6: Permission denied")
print("-" * 70)
explanation = investigate.explain(
    error_message="Permission denied: /var/log/app.log", context="production"
)
print(explanation)

# Example 7: Explain from log entry
print("\n\n🔴 Error 7: From actual log entry")
print("-" * 70)

# Search for an actual error
results = investigate.search(
    files=["examples/logs/production_incident.log"], level="ERROR", limit=1
)

if results.get("results"):
    error_entry = results["results"][0]["entry"]
    print(f"Original error: {error_entry.get('message', 'N/A')}")
    print("\nExplanation:")
    print("-" * 70)
    explanation = investigate.explain(entry=error_entry, context="production")
    print(explanation)

print("\n\n" + "=" * 70)
print("Supported error types:")
print("✓ Timeouts (DB slow, network latency, deadlock)")
print("✓ Connection failures (service down, network issues)")
print("✓ Pool exhaustion (leaks, traffic spikes, slow queries)")
print("✓ Out of memory (leaks, large data, insufficient allocation)")
print("✓ Null references (validation, race conditions)")
print("✓ Permission errors (IAM, file permissions, auth)")
print("")
print("Each explanation includes:")
print("• Plain English description")
print("• Common causes")
print("• Actionable next steps")
print("• Context-specific advice (production vs development)")
print("=" * 70)
