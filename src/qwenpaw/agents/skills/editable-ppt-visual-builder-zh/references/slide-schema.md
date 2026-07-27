# Slide Schema Reference

Use this schema as the handoff from outline/content planning to editable PPT generation.

## Deck Spec

```json
{
  "deck_title": "",
  "audience": "",
  "objective": "",
  "language": "zh-CN",
  "user_facing_language": "zh-CN",
  "user_facing_language_rules": {
    "questions": "use the user's language",
    "option_labels": "use the user's language",
    "scheme_names": "localized display name first; optional English slug second",
    "internal_slugs_allowed": true
  },
  "page_count_target": 12,
  "source_summary": "",
  "delivery_tier": "internal-draft | speaker-assisted-proposal | external-client-ready-proposal | reusable-template-system",
  "commercial_success_criteria": [],
  "known_missing_inputs": [],
  "creative_brief": {
    "audience": "",
    "decision_maker": "",
    "business_stakes": "",
    "desired_belief_shift": "",
    "required_decision_or_action": "",
    "presentation_setting": "sent-ahead | live-meeting | keynote | sales-call | board-review | investor-pitch | training | template-system",
    "presenter_constraints": [],
    "brand_constraints": [],
    "mandatory_content": [],
    "forbidden_claims": [],
    "proof_requirements": [],
    "success_bar": "",
    "approval_owner": ""
  },
  "brand_source_asset_audit": [
    {
      "asset_type": "logo | color | font | template | screenshot | data | diagram | case-proof | legal-note | image | other",
      "status": "provided | missing | placeholder-needed | generate-non-evidence | omit | assumption",
      "path_or_source": "",
      "usage": "",
      "risk_note": ""
    }
  ],
  "review_gates": [
    {
      "gate": "creative-brief | storyboard | visual-direction | design-system | production-qa | delivery-signoff",
      "status": "user-approved | user-delegated | pending | skipped-by-request",
      "decision_rationale": "",
      "risks": []
    }
  ],
  "copy_strategy": {
    "core_message": "",
    "audience_belief_shift": "",
    "headline_style": "",
    "proof_style": "",
    "commercial_highlights": [],
    "must_preserve_wording": [],
    "unsupported_or_missing_proof": [],
    "forbidden_claims": []
  },
  "implementation_strategy": {
    "mode": "native-only | hybrid-layered | template-following",
    "rationale": "",
    "editable_content_boundary": "",
    "raster_asset_boundary": ""
  },
  "commercial_anchor_pages": [
    {
      "slide_number": 0,
      "anchor_type": "before-after | roi | operating-model | roadmap | proof | risk-control | final-ask",
      "buyer_memory": "",
      "proof_needed": ""
    }
  ],
  "storyboard": [
    {
      "slide_number": 0,
      "audience_question": "",
      "narrative_beat": "",
      "claim": "",
      "proof_object": "",
      "commercial_role": "anchor | support | transition | appendix",
      "emotional_intensity": "low | medium | high",
      "information_density": "low | medium | high",
      "expected_action_or_takeaway": "",
      "layout_archetype": "",
      "dependencies": [],
      "approval_status": "approved | delegated | pending | revised"
    }
  ],
  "design_dna_candidates": [
    {
      "name": "",
      "localized_display_name": "",
      "internal_slug": "",
      "commercial_context": "",
      "audience_belief_shift": "",
      "why_it_fits": "",
      "visual_drivers": [],
      "slide_archetypes": [],
      "asset_needs": [],
      "editability_plan": "",
      "risks": [],
      "scores": {
        "commercial_fit": 0,
        "visual_distinction": 0,
        "industry_credibility": 0,
        "editability": 0,
        "deck_wide_scalability": 0,
        "imagegen_promptability": 0,
        "risk_control": 0
      },
      "selected_for_imagegen": false
    }
  ],
  "visual_scheme_selection": {
    "generated_schemes": [
      {
        "scheme_id": "",
        "localized_display_name": "",
        "internal_slug": "",
        "imagegen_prompt": "",
        "imagegen_manifest_path": "",
        "presentation_context": {
          "stage": "visual_scheme",
          "direction_name": "",
          "visual_temperature": "bold | balanced | restrained",
          "dominant_visual_anchor": "",
          "forbidden_patterns": []
        },
        "thumbnail_path": "",
        "contact_sheet_path": "",
        "represented_slide_archetypes": [],
        "visible_to_user": false,
        "notes": ""
      }
    ],
    "regeneration_round": 0,
    "regeneration_history": [
      {
        "round": 0,
        "reason": "none-liked | user-feedback | imagegen-failed | too-generic | off-brief | other",
        "user_feedback": "",
        "strategy": "same-dna-new-compositions | bolder | more-conservative | different-industry-tone | restart-dna-selection",
        "generated_scheme_ids": []
      }
    ],
    "none_liked_option_offered": false,
    "selected_scheme": "",
    "selected_scheme_localized_name": "",
    "selection_source": "user-choice | user-delegated | revised-after-feedback | none-yet",
    "selection_reason": "",
    "rejected_schemes": [],
    "risks_to_control": []
  },
  "visual_translation_contract": {
    "selected_scheme_contact_sheet_path": "",
    "deconstruction_summary": {
      "dominant_visual_drivers": [],
      "page_archetypes": [],
      "dominant_visual_anchors": [],
      "typography_rhythm": "",
      "material_lighting_texture": "",
      "negative_space_rules": "",
      "forbidden_drift": []
    },
    "page_archetype_map": [
      {
        "source_contact_sheet_page": "",
        "production_slide_numbers": [],
        "page_archetype": "cover | thesis | metric-evidence | product-platform | mechanism-process | roadmap | closing | appendix",
        "dominant_visual_anchor": "",
        "focal_ratio": "",
        "editable_text_zone": "",
        "native_raster_split": "",
        "required_page_bound_asset_ids": [],
        "native_component_grammar": "",
        "asset_families_to_omit": [],
        "redesign_trigger": ""
      }
    ],
    "prototype_gate": {
      "required": false,
      "status": "user-approved | user-delegated | revised | cancelled-by-user | pending",
      "prototype_slide_numbers": [],
      "prototype_pptx_path": "",
      "prototype_contact_sheet_path": "",
      "full_size_spot_checks": [],
      "user_facing_options_language": "zh-CN",
      "decision": "",
      "revision_actions": [],
      "risks": []
    }
  },
  "design_system": {
    "style_name": "",
    "selected_design_dna": {
      "name": "",
      "rationale": "",
      "survival_rules": [],
      "risk_controls": []
    },
    "palette": {
      "background": "",
      "surface": "",
      "text": "",
      "muted_text": "",
      "accent": "",
      "accent_2": "",
      "chart_series": []
    },
    "typography": {
      "font_system": {
        "display": "",
        "primary_cjk": "",
        "primary_latin": "",
        "numeric": "",
        "body": "",
        "caption": "",
        "mono_or_code": "",
        "fallback_stack": [],
        "availability": "system-default | verified-installed | provided-font-file | required-user-dependency | assumed-fallback",
        "license_notes": "",
        "embedding_or_delivery_notes": ""
      },
      "type_scale": [
        {
          "role": "cover-title | section-title | slide-title | body | caption | label | metric | callout | footnote",
          "font_role": "display | primary-cjk | primary-latin | numeric | body | caption | mono-or-code",
          "size_pt": "",
          "weight": "",
          "line_spacing": "",
          "usage": ""
        }
      ],
      "rules": {
        "font_pairing_rationale": "",
        "max_font_families": 0,
        "max_weights": 0,
        "cjk_latin_pairing": "",
        "number_treatment": "",
        "fallback_behavior": "",
        "forbidden_defaults": []
      }
    },
    "grid": {
      "margin": "",
      "columns": "",
      "safe_zones": ""
    },
    "master_layout_system": [
      {
        "layout_id": "",
        "name": "cover | section | thesis | summary | evidence | process | architecture | case-proof | roadmap | offer-ask | appendix-table",
        "purpose": "",
        "margins": "",
        "zones": {
          "title": "",
          "body": "",
          "visual": "",
          "footer": "",
          "page_number": ""
        },
        "grid_rules": "",
        "editable_object_rules": "",
        "allowed_variants": [],
        "failure_modes": []
      }
    ],
    "object_grammar": "",
    "chart_grammar": "",
    "information_design_system": {
      "chart_rules": "",
      "table_rules": "",
      "diagram_rules": "",
      "screenshot_rules": "",
      "annotation_rules": "",
      "source_note_rules": "",
      "density_limits": "",
      "evidence_honesty_rules": ""
    },
    "image_grammar": "",
    "visual_drivers": [],
    "motion_system": {
      "default_transition": "",
      "reveal_style": "",
      "pacing_rule": "",
      "step_build_rule": "",
      "static_by_design_rule": ""
    },
    "component_library": [
      {
        "component_id": "",
        "name": "",
        "purpose": "",
        "slide_types": [],
        "native_ppt_parts": [],
        "allowed_raster_layers": [],
        "layout_grammar": "",
        "text_hierarchy": "",
        "variants": [],
        "failure_modes": []
      }
    ],
    "asset_suite_plan": {
      "generation_mode": "asset-sheets | individual-assets | mixed | native-only",
      "source_asset_sheet_count": 0,
      "expected_reusable_element_count": 0,
      "quantity_rationale": "",
      "required_asset_families": [
        "page-bound-hero-asset",
        "icon-pictogram-sheet",
        "module-surface-sheet",
        "connector-node-sheet",
        "data-badge-sheet",
        "texture-background-sheet",
        "section-closing-background",
        "case-image-strip"
      ],
      "preview_gate": {
        "status": "user-approved | user-delegated | skipped-native-only | pending",
        "user_facing_options_language": "zh-CN",
        "decision": "",
        "revision_request": "",
        "risks": []
      },
      "minimum_non_background_family_count": 0,
      "direct_raster_component_budget": {
        "pictogram": "6-12 total direct raster uses for a normal 10-15 slide client-ready deck unless justified",
        "module_surface": "3-8 direct raster uses; repeated content panels should usually be native-redrawn",
        "connector_treatment": "2-6 direct raster motifs; most paths should be native connectors",
        "data_badge": "2-5 direct raster uses",
        "case_image_strip": "2-4 direct raster uses",
        "overuse_rationale": ""
      }
    },
    "asset_usage_matrix": [
      {
        "asset_family": "background | texture | pictogram | module-surface | connector-treatment | data-badge | diagram-accent | case-image-strip | product-platform-visual | signature-mark",
        "asset_ids": [],
        "target_slides": [],
        "component_ids": [],
        "usage_mode": "direct-raster-crop | native-redraw-reference | hybrid | omitted",
        "asset_fitness": "production-ready | reference-only | accent-only | reject",
        "direct_raster_allowed": false,
        "native_redraw_required": false,
        "safe_text_area_required": false,
        "minimum_expected_usage_count": 0,
        "maximum_expected_direct_raster_usage_count": 0,
        "component_integrity_risk": "",
        "fallback_if_unusable": "",
        "omission_rationale": ""
      }
    ],
    "asset_suite": [
      {
        "asset_id": "",
        "path": "",
        "imagegen_manifest_path": "",
        "presentation_context": {
          "stage": "visual_asset",
          "direction_name": "",
          "asset_type": "",
          "reserved_text_area": "",
          "output_role": ""
        },
        "source_asset_sheet_id": "",
        "asset_type": "page-bound-hero-asset | cover-background | section-background | closing-background | body-texture-plate | abstract-scene | photo-metaphor | texture-overlay | signature-mark | pictogram-family | module-surface | connector-treatment | data-badge | diagram-accent | case-image-strip | product-platform-visual",
        "source": "generated | provided | official",
        "target_slides": [],
        "layering_role": "background | midground | foreground-accent | texture | image-panel",
        "usage_mode": "direct-raster-crop | native-redraw-reference | hybrid | omitted",
        "asset_fitness": "production-ready | reference-only | accent-only | reject",
        "direct_raster_approved": false,
        "safe_text_area": "",
        "scaling_rule": "native-redraw | use-original-aspect | 9-slice-safe | full-bleed-16:9 | accent-only | reject",
        "component_integrity_notes": "",
        "text_container_allowed": false,
        "minimum_expected_usage_count": 0,
        "actual_usage_count": 0,
        "translated_to_native": false,
        "crop_notes": "",
        "editability_boundary": ""
      }
    ],
    "post_build_asset_usage_audit": {
      "direct_raster_usage_count": 0,
      "native_translation_usage_count": 0,
      "non_background_family_count_used": 0,
      "zero_usage_generated_families": [],
      "overused_generated_families": [],
      "unsafe_direct_raster_components": [],
      "text_safe_area_failures": [],
      "clipped_or_stretched_components": [],
      "quota_driven_decoration_failures": [],
      "prototype_drift_failures": [],
      "component_integrity_redesign_required": false,
      "visual_translation_contract_failure": false,
      "asset_density_failure": false,
      "background_only_failure": false,
      "redesign_required": false,
      "notes": ""
    }
  },
  "delivery_package": {
    "final_pptx_path": "",
    "contact_sheet_path": "",
    "spot_check_render_paths": [],
    "edit_guide": "",
    "font_fallback_notes": "",
    "asset_usage_notes": "",
    "missing_inputs_and_assumptions": [],
    "commercial_readiness_note": "",
    "signoff_status": "approved | delegated | caveated | draft"
  },
  "slides": []
}
```

## Slide Object

```json
{
  "slide_number": 1,
  "slide_type": "cover | section | summary | chart | table | process | architecture | comparison | roadmap | case-study | closing | appendix",
  "claim": "",
  "title": "",
  "subtitle": "",
  "copy_direction": {
    "source_basis": "",
    "optimized_headline": "",
    "takeaway": "",
    "commercial_highlight": "",
    "proof_gap": "",
    "forbidden_claims": []
  },
  "storyboard_role": {
    "audience_question": "",
    "narrative_beat": "",
    "commercial_role": "anchor | support | transition | appendix",
    "expected_action_or_takeaway": "",
    "layout_archetype": "",
    "approval_status": "approved | delegated | pending | revised"
  },
  "proof_object": {
    "type": "native-chart | native-table | editable-diagram | image | text-argument | mixed",
    "data": {},
    "source": "",
    "notes": ""
  },
  "content_blocks": [
    {
      "role": "headline | body | metric | callout | caption | label | footnote",
      "text": "",
      "priority": 1
    }
  ],
  "typography_usage": {
    "title_role": "cover-title | section-title | slide-title | callout | body | caption | label | metric | footnote",
    "font_role": "display | primary-cjk | primary-latin | numeric | body | caption | mono-or-code",
    "size_role": "",
    "weight": "",
    "line_count_limit": "",
    "fallback_sensitive": false
  },
  "information_design": {
    "decision_question": "",
    "chart_or_diagram_choice": "",
    "choice_rationale": "",
    "evidence_source": "",
    "annotation_strategy": "",
    "source_or_assumption_note": "",
    "density_limit": "",
    "caveat_or_missing_proof": "",
    "editable_evidence_objects": []
  },
  "layout_intent": "",
  "art_direction": {
    "role": "impact | explanation | evidence | transition | decision | closing | appendix",
    "desired_feeling": "",
    "focal_point": "",
    "composition": "",
    "visual_anchor": "",
    "selected_scheme_archetype": "",
    "focal_ratio": "",
    "editable_text_zone": "",
    "visual_translation_rule": "",
    "quota_decoration_risk": "",
    "hierarchy": "",
    "negative_space": "",
    "forbidden_patterns": [],
    "component_id": "",
    "dominant_asset_id": "",
    "redesign_trigger": ""
  },
  "motion_direction": {
    "motion_role": "static-anchor | reveal | contrast | sequence | proof-build | emphasis | transition | payoff",
    "presenter_beat": "",
    "reveal_order": [],
    "object_groups": [
      {
        "group_id": "",
        "objects": [],
        "trigger": "on-click | with-previous | after-previous | slide-load",
        "effect": "appear | fade | wipe | push | zoom | emphasis | none",
        "duration": "instant | short | medium | long"
      }
    ],
    "transition": "cut | fade | push | zoom | wipe | section-break | match-cut | none",
    "pacing": "one-shot | 2-step | 3-step | multi-step | static",
    "implementation_mode": "native-animation | step-build-slides | hybrid | static-by-design",
    "step_build_slides": [],
    "fallback": "",
    "redesign_trigger": ""
  },
  "visual_components": [
    {
      "component": "text-box | shape | chart | table | connector | icon | pictogram | module-surface | data-badge | diagram-accent | image | group",
      "editable": true,
      "purpose": "",
      "content_binding": ""
    }
  ],
  "asset_requirements": [
    {
      "asset_type": "photo | illustration | screenshot | logo | icon | pictogram-family | texture | background | signature-mark | visual-metaphor | module-surface | connector-treatment | data-badge | diagram-accent",
      "source": "provided | generated | official | omitted",
      "editable": false,
      "usage": "",
      "asset_id": "",
      "crop_notes": "",
      "reserved_text_area": ""
    }
  ],
  "asset_usage_bindings": [
    {
      "asset_family": "background | texture | pictogram | module-surface | connector-treatment | data-badge | diagram-accent | case-image-strip | product-platform-visual | signature-mark",
      "asset_id": "",
      "usage_mode": "direct-raster-crop | native-redraw-reference | hybrid | omitted",
      "mapped_component": "",
      "safe_text_area": "",
      "component_integrity_status": "ok | native-redrawn | unsafe | clipped | stretched | omitted",
      "scaling_rule": "native-redraw | use-original-aspect | 9-slice-safe | full-bleed-16:9 | accent-only | reject",
      "actual_usage_count": 0,
      "omission_rationale": ""
    }
  ],
  "visual_qa": {
    "design_dna_fidelity": 0,
    "commercial_fit": 0,
    "composition": 0,
    "focal_point": 0,
    "hierarchy": 0,
    "visual_rhythm": 0,
    "scheme_fidelity": 0,
    "visual_translation_fidelity": 0,
    "prototype_fidelity": 0,
    "typography_system_fidelity": 0,
    "font_availability_safety": 0,
    "master_layout_fidelity": 0,
    "information_design_integrity": 0,
    "evidence_honesty": 0,
    "asset_integration": 0,
    "asset_suite_completeness": 0,
    "asset_fit_quality": 0,
    "component_integrity": 0,
    "text_container_integrity": 0,
    "asset_density_control": 0,
    "quota_driven_decoration_control": 0,
    "raster_scaling_safety": 0,
    "copy_sharpness": 0,
    "motion_reveal_clarity": 0,
    "presentation_rhythm": 0,
    "client_specificity": 0,
    "brand_alignment": 0,
    "handoff_readiness": 0,
    "business_persuasion": 0,
    "self_readability": 0,
    "editability": 0,
    "source_fidelity": 0,
    "redesign_required": false,
    "notes": ""
  },
  "commercial_role": "anchor | support | appendix | transition",
  "qa_notes": ""
}
```

## Componentization Rules

Mark as editable:

- real slide titles, subtitles, captions, bullets, labels, and footnotes
- metrics and numeric callouts
- chart marks, labels, legends, axes, and annotations when source data exists
- table cells
- flow nodes, arrows, connectors, swimlanes, and timeline markers
- cards and comparison blocks
- icons, pictograms, module frames, connector treatments, and data badges when they are implemented as native PPT objects

Art direction requirements:

- the deck has a `creative_brief`, `brand_source_asset_audit`, and review gate record before agency-grade production
- the deck has `user_facing_language` and user-facing questions/options/scheme names follow it
- the deck has a `copy_strategy` before story spine and slide copy are finalized
- the deck has a storyboard before visual exploration and final production
- high-stakes decks record storyboard approval or delegated storyboard approval
- the deck has 3-5 design DNA candidates scored before visual scheme prompting
- only 2-3 selected design DNA finalists proceed to imagegen visual schemes
- the final deck build does not begin until `visual_scheme_selection` records user choice or explicit delegated choice
- `visual_scheme_selection.generated_schemes` contains visible imagegen thumbnail/contact-sheet paths before the user is asked to choose
- every generated visual scheme and downstream visual asset records its sibling `*.imagegen.json` path and structured `presentation_context`; downstream asset `direction_name` values match the selected scheme exactly
- `visual_scheme_selection.none_liked_option_offered` is true whenever visual schemes are presented
- if the user dislikes all visual schemes, `visual_scheme_selection.regeneration_history` records the new batch reason and strategy
- the deck has a `visual_translation_contract` after visual scheme selection and before editable PPT production
- client-ready or highly visual decks record `visual_translation_contract.prototype_gate.status` as `user-approved`, `user-delegated`, `revised`, or `cancelled-by-user` before full deck production
- every key visual slide has a page-archetype mapping with dominant visual anchor, focal ratio, editable text zone, native/raster split, and omitted asset families when relevant
- the deck has a `design_system.typography.font_system` with font roles, fallback stack, availability, and delivery notes
- the deck has a `design_system.typography.type_scale` before editable slides are built
- the deck has a `design_system.master_layout_system` before editable slides are built
- the deck has a `design_system.information_design_system` before data, diagram, table, roadmap, or evidence-heavy slides are built
- hybrid client-ready decks have a `design_system.asset_suite_plan` before editable slides are built
- when `asset_suite_plan.generation_mode` is `asset-sheets` or `mixed`, `source_asset_sheet_count` and `expected_reusable_element_count` are recorded with a quantity rationale
- when more than 10 source asset sheets are planned, `asset_suite_plan.quantity_rationale` explains why the deck needs that many
- client-ready hybrid decks record `asset_suite_plan.preview_gate.status` as `user-approved`, `user-delegated`, or `skipped-native-only` before PPTX generation
- hybrid client-ready decks with generated assets have `design_system.asset_usage_matrix` before editable slides are built
- every generated non-background asset family is represented in `design_system.asset_usage_matrix` as direct use, native translation, hybrid use, or deliberate omission
- every generated component asset has an asset fitness classification before direct use
- direct raster component families have maximum expected usage counts as well as minimum counts
- every direct raster component used as or near a text container has a safe text area, scaling rule, and component integrity status
- every slide that should use generated component assets records `asset_usage_bindings` with a mapped component or omission rationale
- if a generated family is not marked `omitted`, final QA records its direct or native usage in `post_build_asset_usage_audit`
- zero-use generated component families, or background/texture-only usage, mark the deck as needing redesign unless the omission was approved before PPTX generation
- overused generated component families, unsafe direct raster components, text-safe-area failures, or clipped/stretched components mark the deck as needing redesign unless the deck records a deliberate exception and passes full-size QA
- `quota_driven_decoration_failures`, `prototype_drift_failures`, or `visual_translation_contract_failure` mark the deck as needing redesign unless the user explicitly accepts the downgrade
- every non-appendix slide has `art_direction.role`
- every non-appendix slide has `copy_direction.optimized_headline` or a deliberate reason to preserve source wording
- every non-appendix slide has `storyboard_role`
- every non-appendix slide has `typography_usage` tied to the deck type scale
- every non-appendix slide has one `focal_point`
- every non-appendix key visual slide has `selected_scheme_archetype`, `focal_ratio`, `editable_text_zone`, and `visual_translation_rule`
- every non-appendix slide has `motion_direction` or a clear `static-by-design` reason
- every reveal/build slide has object groups and an implementation mode
- every slide that uses generated imagery states `dominant_asset_id` or asset requirements
- every repeated page pattern references a `component_id`
- every slide has a `redesign_trigger` that describes what would make it feel weak or template-like
- client-ready decks identify 2-3 `commercial_role: "anchor"` slides
- anchor slides have buyer-facing proof, implementation logic, ROI/personnel impact, risk control, or a final ask

Allow raster only for:

- photos
- generated illustrations
- background textures
- full-bleed or partial-bleed hero backgrounds
- section and closing backgrounds
- decorative marks, brush strokes, lighting, material textures, and atmospheric overlays
- decorative visual metaphors
- generated pictogram families, connector treatments, module surfaces, and data badges when they are intentionally non-text visual assets
- screenshots that are meant to document an external UI
- selected visual direction thumbnails used as references, not deck pages

When raster assets are used, keep them as separate PowerPoint image objects. Do not bake editable slide content into them.

Direct raster component rules:

- use direct raster components only when `asset_fitness` is `production-ready`
- use `reference-only` assets to redraw native PPT components, not as text containers
- do not stretch fixed-aspect raster panels, badges, cards, input boxes, or connector frames into different shapes
- do not use `fit: "cover"` on raster components whose frame, border, corner, or internal decoration must remain intact
- if editable text appears visually inside a component, the slide must define a safe text area and the full-size rendered preview must show the text inside it
- prefer native redraw for repeated content-bearing cards, module surfaces, data badges, connector paths, and input boxes

## Visual QA Rules

After rendering previews:

- fill `visual_qa` scores from 1 to 5
- mark `redesign_required: true` when design DNA fidelity, commercial fit, composition, focal point, hierarchy, motion/reveal clarity, presentation rhythm, or scheme fidelity is below 4
- mark `redesign_required: true` when visual translation fidelity, prototype fidelity, or quota-driven decoration control is below 4
- mark `redesign_required: true` when typography system fidelity or font availability safety is below 4
- mark `redesign_required: true` when master layout fidelity, information design integrity, evidence honesty, brand alignment, or handoff readiness is below 4
- mark `redesign_required: true` when asset suite completeness or copy sharpness is below 4
- mark `redesign_required: true` when asset fit quality, component integrity, text container integrity, asset density control, or raster scaling safety is below 4
- mark `redesign_required: true` when `post_build_asset_usage_audit.background_only_failure` is true
- mark `redesign_required: true` when generated pictogram, module-surface, connector-treatment, data-badge, diagram-accent, case-image-strip, or signature-mark families have zero usage without a pre-recorded omission rationale
- mark `redesign_required: true` when `post_build_asset_usage_audit.asset_density_failure`, `component_integrity_redesign_required`, `unsafe_direct_raster_components`, `text_safe_area_failures`, or `clipped_or_stretched_components` indicates a real issue
- mark `redesign_required: true` when `post_build_asset_usage_audit.visual_translation_contract_failure`, `prototype_drift_failures`, or `quota_driven_decoration_failures` indicates a real issue
- for client-ready decks, mark `redesign_required: true` when an anchor slide scores below 4 on client specificity, business persuasion, or self-readability
- redesign weak commercial DNA by changing the selected DNA, prompt, component grammar, asset crop, or page archetype
- redesign weak slides by changing composition, component choice, asset crop, type scale, or visual hierarchy
- redesign quota-driven decoration by removing the disconnected asset and updating the asset usage matrix rather than adding another decorative asset
- redesign weak motion by changing reveal order, object grouping, transition, or step-build slide variants
- do not use screenshot flattening to bypass weak editable layouts

## Pre-PPTX Builder Checklist

Before building the PPTX, confirm:

- creative brief and agency success bar are complete
- user-facing questions, visual scheme names, and selectable options are localized; for Chinese users, they are Chinese-first
- brand/source asset audit is complete and missing inputs are classified
- review gates are recorded, including storyboard approval/delegation for high-stakes work
- the user has selected a visual scheme or delegated the choice
- the user saw generated image thumbnails/contact sheets before visual scheme selection, unless the user explicitly canceled the visual-selection workflow
- the user had a clear "none of these / regenerate another batch" option at visual selection
- the visual scheme selection checkpoint is recorded in the deck spec
- the visual translation contract is complete after visual scheme selection: page archetypes, dominant visual anchors, focal ratios, editable text zones, native/raster split, and forbidden drift
- client-ready or highly visual decks have rendered 3-5 slide editable PPT prototype evidence, approval/delegation/revision record, or explicit user cancellation before full production
- optimized copy strategy and commercial highlights are complete
- typography/font system is complete, including font availability, fallback stack, type scale, and delivery caveats
- master layout system is complete
- information design system is complete for charts, tables, diagrams, screenshots, roadmaps, and evidence-heavy pages
- `presentation_builder` is available in the current tool list for final PPTX export
- the authoring route is explicit: template clone/edit -> `template_following`, selected visual scheme -> `custom_compose`, otherwise -> `codex_grid`
- every selected-scheme `custom_compose` slide has an archetype, named editable layers with exact bounds, and `expected_content` assertions for business-critical text, objects, and repeated semantic groups
- the declared custom-compose font family or one of its ordered fallbacks is verified in the render environment; a font name alone is not proof of availability
- required generated images are listed in `required_image_assets`
- generated image usage is recorded in `asset_usage_matrix` with concrete 1-based slide indexes before PPTX generation
- 3-5 design DNA candidates have been scored and 2-3 finalists selected before imagegen prompting
- no selected DNA imitates a specific paid template, marketplace item, brand, or protected designer style
- every slide has a claim
- every slide has storyboard role and narrative beat
- every slide has optimized headline/takeaway guidance or a source-preservation note
- every slide uses the deck typography system rather than unspecified defaults
- every slide has a proof object or an intentional visual role
- every non-appendix slide has art direction
- every non-appendix slide has motion direction or an explicit static-by-design reason
- the design component library exists and covers repeated slide patterns
- every important text element is represented as text, not an image
- no real slide text is rasterized only to preserve a font appearance
- premium or brand fonts are verified, provided, or marked as required user dependencies
- every chart/table either has source data or is clearly marked as conceptual
- every information-heavy slide has chart/diagram/table choice rationale, annotation strategy, density limit, and source/caveat note
- no chart, diagram, screenshot, or metric implies unsupported evidence
- all required brand or identity assets are provided or safely omitted
- the delivery tier and commercial success criteria are known
- missing client-specific inputs are recorded rather than invented
- 2-3 commercial anchor pages are planned for client-ready decks
- native-only versus hybrid-layered implementation has been chosen deliberately
- imagery-heavy selected schemes have a visual asset suite before PPT generation starts
- client-ready hybrid decks have either visible asset-sheet previews or an explicit delegated/native-only rationale before PPT generation starts
- asset suite quantity is intentional: normally 6-10 source asset sheets for a 10-15 slide deck, with more than 10 justified
- a background-only asset set has been rejected unless the design is deliberately native-only and passes QA
- each generated asset has a usage target, crop note, and editability boundary
- `design_system.asset_usage_matrix` maps generated asset families to exact target slides and component roles before PPTX generation
- post-build package QA confirms required image assets produced embedded PPTX media (`media_count > 0`) and picture nodes (`pic_count > 0`)
- at least 4 non-background asset families are planned for visible use or native translation in a 10-15 slide client-ready hybrid deck, unless the deck records an approved omission rationale
- every generated component-like asset has an asset fitness gate result before direct raster use
- every direct raster component family has a density budget and overuse rationale when the budget is exceeded
- every planned raster text container has a safe text area and scaling rule; unsafe component sheets are converted to native redraw references
- required pictogram families, connector treatments, module surfaces, data badges, and diagram accents are planned or intentionally omitted
- every approved generated component family has a post-build direct-use, native-translation, or deliberate-omission audit
- the final deck will preserve the selected scheme's visual anchors, not just its palette
- assets are used only when they support the story, information design, or composition; no asset is placed solely to satisfy a usage target
- native animation support has been confirmed or step-build slide variants are planned for reveal-heavy slides
- the target PPTX path and title are known
- delivery package plan exists: final PPTX, contact sheet, spot checks, edit guide, font notes, asset notes, caveats, and signoff status
