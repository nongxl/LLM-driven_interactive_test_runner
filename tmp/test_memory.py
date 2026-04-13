import sys
import os
import json

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.state_memory import StateMemory

def test_state_memory():
    memory = StateMemory(max_history=120)
    
    print("Testing 120 steps recording...")
    for i in range(120):
        action = {"action": "click", "name": f"Button_{i}", "ref": f"e{i}"}
        snapshot = {"url": f"http://example.com/page_{i//10}", "aria_text": f"heading \"Page Title {i//10}\""}
        memory.record_step(action, snapshot)
        
    print(f"Total steps in history: {len(memory.history)}")
    
    summary = memory.get_history_summary(max_detailed=10)
    print("\n--- Summary Output ---")
    print(summary)
    print("----------------------")
    
    # Check if condensed memory is present
    assert "... (前 110 步操作已略" in summary
    assert "[Step 1] click @ http://example.com/page_0" in summary
    assert "[Step 101] click @ http://example.com/page_10" in summary
    # Check if detailed memory (last 10) is present
    assert "Button_119" in summary
    assert "Button_110" in summary
    assert "Button_109" not in summary # Only last 10 are detailed
    
    print("\n✅ StateMemory Unit Test Passed!")

if __name__ == "__main__":
    test_state_memory()
