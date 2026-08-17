#!/usr/bin/env python3
"""Test script for Mem0 plugin with real API key."""

import asyncio
import os
import sys

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.services.memory_provider_plugin_loader import PluginLoader
from nexent.memory.models import MemorySearchRequest


async def test_mem0_plugin():
    """Test Mem0 plugin with real API key from environment."""
    
    api_key = os.getenv("MEM0_API_KEY")
    if not api_key:
        print("❌ MEM0_API_KEY not found in environment")
        return False
    
    print(f"✓ Found API key: {api_key[:10]}...{api_key[-4:]}")
    
    print("\n📦 Loading plugins...")
    loader = PluginLoader()
    loader.load_all()
    
    plugins = loader.list_plugins()
    print(f"✓ Loaded {len(plugins)} plugin(s)")
    
    mem0_plugin = None
    for plugin in plugins:
        if plugin.name == "mem0":
            mem0_plugin = plugin
            break
    
    if not mem0_plugin:
        print("❌ Mem0 plugin not found")
        return False
    
    print(f"✓ Found Mem0 plugin v{mem0_plugin.version}")
    print(f"  Implements: {', '.join(mem0_plugin.implements)}")
    
    print("\n🔧 Creating provider instance...")
    config = {
        "plugin.name": "mem0",
        "plugin.api_key": api_key,
        # base_url will default to https://api.mem0.ai
    }
    
    provider = loader.build_provider("mem0", config)
    print(f"✓ Provider created: {provider.provider_name}")
    
    print("\n🔍 Testing search...")
    search_request = MemorySearchRequest(
        query="What are the user's boundaries and preferences?",
        user_id="playground-ai-companion-ac343094",
        limit=10
    )
    
    try:
        results = await provider.search(search_request, limit=10)
        print(f"✓ Search returned {len(results)} result(s)")
        
        if len(results) == 0:
            print("⚠️  No results found")
            return False
        
        print("\n📋 Search Results:")
        print("-" * 80)
        for i, result in enumerate(results, 1):
            print(f"\n{i}. Score: {result.score:.3f}")
            print(f"   ID: {result.external_id}")
            print(f"   Content: {result.content[:100]}...")
            if result.metadata:
                print(f"   Categories: {result.metadata.get('categories', [])}")
        
        print("\n" + "-" * 80)
        print(f"✓ Successfully retrieved {len(results)} memories from Mem0 cloud")
        return True
        
    except Exception as e:
        print(f"❌ Search failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 80)
    print("Mem0 Plugin Test - Real API Key")
    print("=" * 80)
    
    success = asyncio.run(test_mem0_plugin())
    
    print("\n" + "=" * 80)
    if success:
        print("✅ Test PASSED")
        sys.exit(0)
    else:
        print("❌ Test FAILED")
        sys.exit(1)
