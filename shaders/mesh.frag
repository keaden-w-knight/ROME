#version 450

layout(location = 0) in vec3 v_normal;
layout(location = 1) in vec3 v_color;
layout(location = 0) out vec4 out_color;

// Lighting: a key light, a dimmer fill from the other side to lift shadowed
// faces, and ambient. The albedo is the per-instance colour. The roadmap's
// lighting phase replaces the fixed lights with a positioned light.
const vec3 KEY_DIR = normalize(vec3(-0.5, 0.8, -1.0));
const vec3 FILL_DIR = normalize(vec3(0.6, 0.35, 0.8));
const float AMBIENT = 0.22;
const float FILL = 0.35;

void main() {
    vec3 n = normalize(v_normal);
    float key = max(dot(n, KEY_DIR), 0.0);
    float fill = max(dot(n, FILL_DIR), 0.0) * FILL;
    float light = AMBIENT + key + fill;
    out_color = vec4(min(v_color * light, vec3(1.0)), 1.0);
}
