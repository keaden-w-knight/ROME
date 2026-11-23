#version 450

layout(push_constant) uniform Push {
    mat4 mvp;
    mat4 model;
    vec4 color;        // rgb albedo
    vec4 light_pos;    // xyz world position, w = ambient
    vec4 light_color;  // rgb colour,        w = specular strength
    vec4 eye;          // xyz camera position, w = shininess
} pc;

layout(location = 0) in vec3 v_normal;
layout(location = 1) in vec3 v_color;
layout(location = 2) in vec3 v_worldpos;
layout(location = 0) out vec4 out_color;

void main() {
    vec3 n = normalize(v_normal);

    // Point light with gentle distance attenuation.
    vec3 to_light = pc.light_pos.xyz - v_worldpos;
    float dist = length(to_light);
    vec3 l = to_light / max(dist, 1e-4);
    float atten = 1.0 / (1.0 + 0.02 * dist + 0.008 * dist * dist);

    float diffuse = max(dot(n, l), 0.0) * atten;

    // Blinn-Phong specular — view-dependent, so the highlight tracks the camera.
    vec3 view = normalize(pc.eye.xyz - v_worldpos);
    vec3 half_vec = normalize(l + view);
    float spec = pow(max(dot(n, half_vec), 0.0), max(pc.eye.w, 1.0)) * pc.light_color.w * atten;

    float ambient = pc.light_pos.w;
    vec3 lit = v_color * (ambient + diffuse * pc.light_color.rgb) + pc.light_color.rgb * spec;
    out_color = vec4(min(lit, vec3(1.0)), 1.0);
}
