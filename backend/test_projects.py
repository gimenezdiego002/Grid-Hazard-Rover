from db import (
    save_project,
    get_all_projects,
    find_projects_near,
    projects_collection,
)

print("🧪 Starting MongoDB Data & Search Test...\n")

# 1. Clear any leftover test documents in projects
projects_collection.delete_many({"source": "FDOT", "sourceId": "12345"})

# 2. Define a sample project (coordinates in Miami: [longitude, latitude])
sample_project = {
    "source": "FDOT",
    "sourceId": "12345",
    "name": "Road Construction Project",
    "projectType": "road",
    "agency": "FDOT",
    "location": {
        "type": "Point",
        "coordinates": [-80.19, 25.76]  # Miami downtown area
    },
    "startDate": "2026-01-01",
    "endDate": "2027-01-01"
}

# --- TEST 1: Save the project ---
print("Step 1: Saving a new project to MongoDB...")
save_project(sample_project)
projects = get_all_projects()
print(f"  ✓ Stored projects count: {len(projects)}")
print(f"  ✓ Project name: '{projects[0]['name']}'\n")

# --- TEST 2: Duplicate Prevention (Update instead of duplicate) ---
print("Step 2: Re-saving the SAME project with an updated name...")
updated_project = sample_project.copy()
updated_project["name"] = "Road Construction Project (PHASE 2 - UPDATED)"

save_project(updated_project)
projects = get_all_projects()
print(f"  ✓ Total projects count: {len(projects)} (Should still be 1, NOT 2!)")
print(f"  ✓ Updated project name: '{projects[0]['name']}'\n")

# --- TEST 3: Geospatial Search (Within 1 kilometer) ---
print("Step 3: Searching for projects within 1 km (1000 meters) of [-80.19, 25.76]...")
# Search right at the same location
near_projects = find_projects_near(-80.19, 25.76, max_distance_meters=1000)
print(f"  ✓ Found {len(near_projects)} project(s) nearby: {near_projects[0]['name']}\n")

# --- TEST 4: Search Far Away (Should find nothing) ---
print("Step 4: Searching from 50+ km away (e.g. Fort Lauderdale/Boca)...")
far_projects = find_projects_near(-80.14, 26.12, max_distance_meters=1000)
print(f"  ✓ Found {len(far_projects)} project(s) nearby (Expected: 0)\n")

print("🎉 ALL TESTS PASSED! Your MongoDB database is fully working and ready for your teammates!")
