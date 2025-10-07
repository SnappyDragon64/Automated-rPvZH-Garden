import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from .plant_helper import PlantHelper


class FusionHelper:
    """Encapsulates all logic related to plant and item fusion."""

    def __init__(self, fusions_list: List[Dict[str, Any]], materials_data: Dict[str, str], plant_helper: PlantHelper):
        self.all_fusions = fusions_list
        self.all_materials = materials_data
        self.all_materials_by_name = set(materials_data.values())
        self.all_fusions_by_id = {f['id']: f for f in fusions_list}
        self.all_fusions_by_name = {f['name']: f for f in fusions_list if 'name' in f}
        self.plant_helper = plant_helper

        self.visible_fusions: List[Dict[str, Any]] = []
        self.hidden_fusions_by_id: Dict[str, Dict[str, Any]] = {}

        for f in self.all_fusions:
            visibility = f.get("visibility", "visible")

            if visibility == "visible":
                self.visible_fusions.append(f)
            elif visibility == "hidden":
                self.hidden_fusions_by_id[f['id']] = f

    def find_defined_fusion(self, query: str) -> Optional[Dict[str, Any]]:
        """Searches for a fusion definition by ID or name (case-insensitive)."""

        query_lower = query.lower()

        for f_def in self.all_fusions:
            if f_def.get("id", "").lower() == query_lower:
                return f_def.copy()

        for f_def in self.all_fusions:
            if f_def.get("name", "").lower() == query_lower:
                return f_def.copy()

        return None

    def format_recipe_string(self, recipe_ids: List[str]) -> str:
        """Formats a list of component IDs into a displayable string like '`PlantA` + `PlantB`'."""
        if not recipe_ids:
            return "Unknown Recipe"

        component_names = []
        for comp_id in recipe_ids:
            name = comp_id
            if base_plant := self.plant_helper.get_base_plant_by_id(comp_id):
                name = base_plant.get("name", comp_id)
            elif fusion_def := self.find_defined_fusion(comp_id):
                name = fusion_def.get("name", comp_id)
            component_names.append(f"`{name}`")

        if len(component_names) > 12:
            return " + ".join(component_names[:12]) + " + ..."
        return " + ".join(component_names)

    def deconstruct_plant(
            self,
            plant_data: Dict[str, Any],
            path: Optional[set] = None
    ) -> Tuple[List[str], List[str]]:
        """Recursively deconstructs a plant into its base material and plant component names."""
        if path is None:
            path = set()

        plant_id = plant_data.get("id")
        plant_name = plant_data.get("name", plant_id)

        if plant_id in path:
            return [], [f"Infinite recursion detected involving '{plant_name}'."]
        path.add(plant_id)

        if plant_data.get("type") == "material" or plant_name in self.all_materials_by_name:
            return [plant_name], []

        if plant_data.get("type") == "base_plant":
            return [plant_name], []

        fusion_def = self.all_fusions_by_id.get(plant_id)
        if not fusion_def or "recipe" not in fusion_def:
            return [], [f"Recipe for fusion '{plant_name}' is missing."]

        final_components: List[str] = []
        errors: List[str] = []

        all_base_plants_by_name = {p['name']: p for p in self.plant_helper.base_plants if 'name' in p}

        for component_name in fusion_def.get("recipe", []):
            if component_name in all_base_plants_by_name:
                final_components.append(component_name)
            elif component_name in self.all_materials_by_name:
                final_components.append(component_name)
            elif component_name in self.all_fusions_by_name:
                next_fusion_def = self.all_fusions_by_name[component_name]
                sub_components, sub_errors = self.deconstruct_plant(next_fusion_def, path.copy())
                final_components.extend(sub_components)
                errors.extend(sub_errors)
            else:
                errors.append(f"Recipe for '{plant_name}' contains unknown component: '{component_name}'.")

        return final_components, errors

    def find_fusion_match(self, components: List[str]) -> Optional[Dict[str, Any]]:
        """Given a list of base component names, finds a matching fusion recipe."""

        input_recipe_counter = Counter(components)

        for fusion_def in self.all_fusions:
            recipe_counter = Counter(fusion_def.get("recipe", []))

            if recipe_counter and recipe_counter == input_recipe_counter:
                return fusion_def

        return None

    def parse_almanac_args(self, full_args: str) -> dict:
        """Parses filters and a page number from a single string."""

        filters = []
        page = 1

        if not full_args or not full_args.strip():
            return {'filters': filters, 'page': page}

        words = full_args.strip().split()
        if words[-1].isdigit():
            page = int(words.pop())

        filter_string = " ".join(words)
        if not filter_string:
            return {'filters': filters, 'page': page}

        filter_parts = re.split(r'\s+(?=\w+:)', filter_string)

        for part in filter_parts:
            if ":" in part:
                key, value = part.split(":", 1)
                filters.append({'key': key.strip().lower(), 'value': value.strip().lower()})

        return {'filters': filters, 'page': page}

    def apply_almanac_filters(self, fusions_list: List[dict], filters: List[dict], discovered_ids: set, **kwargs) -> \
            List[dict]:
        """Applies a list of parsed filters to a list of fusion definitions."""

        if not filters:
            return fusions_list

        filtered_results = list(fusions_list)
        mat_ids_to_names = self.all_materials
        mat_names_to_ids = {v.lower(): k for k, v in mat_ids_to_names.items()}
        plans_by_fusion_id = kwargs.get("plans_by_fusion_id", {})

        for f_filter in filters:
            key, value = f_filter['key'], f_filter['value']

            if key == 'name':
                filtered_results = [f for f in filtered_results if value in f.get('name', '').lower()]
            elif key == 'contains':
                temp_results = []
                searched_fusion = self.find_defined_fusion(value)

                if searched_fusion:
                    search_recipe_counter = Counter(searched_fusion.get('recipe', []))

                    for f in filtered_results:
                        recipe_counter = Counter(f.get('recipe', []))
                        is_subset = all(recipe_counter[item] >= count for item, count in search_recipe_counter.items())

                        if is_subset:
                            temp_results.append(f)
                else:
                    for f in filtered_results:
                        for component_name in f.get('recipe', []):
                            if value in component_name.lower():
                                temp_results.append(f)
                                break

                            component_id = mat_names_to_ids.get(component_name.lower())

                            if component_id and value in component_id:
                                temp_results.append(f)
                                break

                filtered_results = temp_results
            elif key == 'discovered':
                is_true = value == 'true'
                filtered_results = [f for f in filtered_results if (f.get('id') in discovered_ids) == is_true]
            elif key == 'storage':
                if not plans_by_fusion_id:
                    continue

                if value == 'false':
                    temp_results = []

                    for f in filtered_results:
                        plan = plans_by_fusion_id.get(f['id'])

                        if plan and not any(asset.get("source") == "storage" for asset in plan):
                            temp_results.append(f)

                    filtered_results = temp_results
            elif key == 'tier':
                normalized_value = "tier" + value.lower().replace("infinity", "∞").replace("inf", "∞").replace("tier",
                                                                                                               "")
                filtered_results = [f for f in filtered_results if f.get('type', '').lower() == normalized_value]
            elif key == 'missing':
                pass

        return filtered_results

    def get_user_whole_assets_with_source(self, user_data: dict) -> List[dict]:
        """Gathers all user assets, tagging them with source and index."""

        assets = []

        for i, plant in enumerate(user_data.get("garden", [])):
            if isinstance(plant, dict) and plant.get("type") != "seedling":
                assets.append({**plant, "source": "garden", "index": i})

        for i, plant in enumerate(user_data.get("storage_shed_slots", [])):
            if isinstance(plant, dict):
                assets.append({**plant, "source": "storage", "index": i})

        for item_id in user_data.get("inventory", []):
            if item_name := self.all_materials.get(item_id):
                assets.append(
                    {"name": item_name, "id": item_id, "type": "material", "source": "inventory", "index": -1})

        return assets

    def get_valid_crafting_components(self, assets_list: List[dict]) -> List[dict]:
        """Filters a list of assets to return only those valid for use as fusion components."""

        validated_assets = []
        for asset in assets_list:
            asset_type = asset.get("type")

            if asset_type == "material" or asset_type == "base_plant":
                validated_assets.append(asset)
                continue

            fusion_def = self.all_fusions_by_id.get(asset.get("id"))

            if not fusion_def or not fusion_def.get("recipe"):
                continue

            validated_assets.append(asset)

        return validated_assets

    def find_crafting_plan(
            self,
            recipe_counter: Counter,
            user_assets: List[dict],
            fusion_id_to_check: str
    ) -> Tuple[Optional[List[dict]], Counter]:
        """
        Determines if a recipe can be crafted and returns the plan and any remaining needed components.
        This function respects the "inseparable unit" rule for fused components.
        If a `fusion_id_to_check` is provided, this function will proactively ignore any
        assets matching that ID before attempting to find a crafting plan.
        It also filters out any fusion plants that lack a valid recipe definition.
        """

        temp_assets = user_assets
        if fusion_id_to_check:
            temp_assets = [asset for asset in user_assets if asset.get("id") != fusion_id_to_check]

        effective_assets = self.get_valid_crafting_components(temp_assets)

        needed = recipe_counter.copy()

        sorted_assets = sorted(
            effective_assets,
            key=lambda x: len(self.deconstruct_plant(x)[0]),
            reverse=True
        )
        plan = []

        for asset in sorted_assets:
            asset_components, errors = self.deconstruct_plant(asset)

            if errors:
                continue

            asset_counter = Counter(asset_components)

            if all(needed.get(item, 0) >= count for item, count in asset_counter.items()):
                needed -= asset_counter
                plan.append(asset)

        remaining_needs = Counter({k: v for k, v in needed.items() if v > 0})

        if not remaining_needs:
            return plan, Counter()

        return None, remaining_needs