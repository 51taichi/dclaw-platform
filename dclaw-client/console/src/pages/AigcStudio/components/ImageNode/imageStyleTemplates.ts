import type { AigcStyleTemplate } from "../../../../api/modules/aigcStudio";

export function imageStyleTemplateData(template: AigcStyleTemplate) {
  const supplementalPrompt = template.supplemental_prompt ?? "";
  const referenceImageUrls = template.reference_image_urls ?? [];
  return {
    styleTemplateId: template.id,
    stylePreset: template.title,
    styleRuntimeMode: template.runtime_mode,
    activeTool: "style",
    styleReferenceThumb: true,
    styleReferenceName: template.title,
    styleReferencePreviewUrl: template.cover_url ?? null,
    styleTemplateUuid: template.effect_template_uuid ?? null,
    effectTemplateUuids: template.effect_template_uuid
      ? [template.effect_template_uuid]
      : null,
    effectId: template.effect_id ?? null,
    effects:
      template.effect_id !== undefined && template.effect_id !== null
        ? [template.effect_id]
        : null,
    styleKeywords: template.keywords,
    styleDescription: template.description,
    styleSupplementalPrompt: supplementalPrompt,
    stylePromptTemplate:
      template.type === "play" ? template.prompt_template ?? "" : "",
    visualDna: template.visual_dna ?? [],
    styleReferenceImages: referenceImageUrls,
    aestheticProfileSnapshot: {
      id: template.id,
      title: template.title,
      version: template.profile_version ?? "1.0",
      model_family: template.model_family ?? null,
      visual_dna: template.visual_dna ?? [],
      supplemental_prompt: supplementalPrompt,
      reference_image_urls: referenceImageUrls,
    },
    imageProgress: null,
    inputUpdated: true,
  };
}
