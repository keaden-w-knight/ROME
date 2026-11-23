#version 450

// Per-vertex: position and normal from the bound vertex buffer.
layout(location = 0) in vec3 in_position;
layout(location = 1) in vec3 in_normal;

// Per-draw push constant. The light fields are the same for every draw in a
// frame; carrying them here keeps the renderer free of descriptor sets. 192
// bytes — within the 256-byte push limit of the target GPUs.
layout(push_constant) uniform Push {
    mat4 mvp;
    mat4 model;
    vec4 color;        // rgb albedo
    vec4 light_pos;    // xyz world position, w = ambient
    vec4 light_color;  // rgb colour,        w = specular strength
    vec4 eye;          // xyz camera position, w = shininess
} pc;

layout(location = 0) out vec3 v_normal;
layout(location = 1) out vec3 v_color;
layout(location = 2) out vec3 v_worldpos;

void main() {
    gl_Position = pc.mvp * vec4(in_position, 1.0);
    v_worldpos = (pc.model * vec4(in_position, 1.0)).xyz;
    v_normal = mat3(pc.model) * in_normal;
    v_color = pc.color.rgb;
}
