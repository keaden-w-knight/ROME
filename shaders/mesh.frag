#version 450

layout(location = 0) in vec3 v_normal;
layout(location = 0) out vec4 out_color;

// Phase 1 lighting: a fixed directional light and one base colour. The roadmap's
// lighting phase replaces these with a positioned light + per-node material.
const vec3 LIGHT_DIR = normalize(vec3(-0.5, 0.8, -1.0));
const vec3 ALBEDO = vec3(0.55, 0.62, 0.78);
const float AMBIENT = 0.15;

void main() {
    vec3 n = normalize(v_normal);
    float diffuse = max(dot(n, LIGHT_DIR), 0.0);
    float light = AMBIENT + (1.0 - AMBIENT) * diffuse;
    out_color = vec4(ALBEDO * light, 1.0);
}
