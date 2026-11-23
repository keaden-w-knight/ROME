#version 450

// Per-vertex: position and normal from the bound vertex buffer.
layout(location = 0) in vec3 in_position;
layout(location = 1) in vec3 in_normal;

// Per-draw push constant: transform + albedo (144 bytes).
layout(push_constant) uniform Push {
    mat4 mvp;
    mat4 model;
    vec4 color;
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
