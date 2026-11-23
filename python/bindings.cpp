#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/vector.h>

#include <cstdint>
#include <tuple>
#include <vector>

#include "rome/app.hpp"
#include "rome/error.hpp"
#include "rome/types.hpp"
#include "rome/window.hpp"

namespace nb = nanobind;
using namespace nb::literals;

namespace {

/// Colours are accepted as (r, g, b) or (r, g, b, a) tuples, which is what a
/// pygame user will reach for first.
rome::Color color_from_tuple(const nb::tuple& value) {
    const std::size_t size = nb::len(value);
    if (size != 3 && size != 4) {
        throw nb::value_error("colour must be a 3- or 4-tuple of floats in 0..1");
    }
    rome::Color color{};
    color.r = nb::cast<float>(value[0]);
    color.g = nb::cast<float>(value[1]);
    color.b = nb::cast<float>(value[2]);
    color.a = size == 4 ? nb::cast<float>(value[3]) : 1.0F;
    return color;
}

nb::tuple color_to_tuple(rome::Color color) {
    return nb::make_tuple(color.r, color.g, color.b, color.a);
}

rome::CameraParams make_camera(const std::tuple<float, float, float>& pos,
                               const std::tuple<float, float, float>& target,
                               const std::tuple<float, float, float>& up, float fov) {
    rome::CameraParams c{};
    c.position[0] = std::get<0>(pos);
    c.position[1] = std::get<1>(pos);
    c.position[2] = std::get<2>(pos);
    c.target[0] = std::get<0>(target);
    c.target[1] = std::get<1>(target);
    c.target[2] = std::get<2>(target);
    c.up[0] = std::get<0>(up);
    c.up[1] = std::get<1>(up);
    c.up[2] = std::get<2>(up);
    c.fov_deg = fov;
    return c;
}

/// Parse a Python list of lights, each a tuple:
/// (type, (x,y,z), (dx,dy,dz), (r,g,b), intensity, range, inner_cos, outer_cos).
std::vector<rome::Light> parse_lights(const nb::list& lights) {
    std::vector<rome::Light> out;
    const std::size_t count = nb::len(lights);
    out.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
        nb::tuple t = nb::cast<nb::tuple>(lights[i]);
        rome::Light l{};
        l.type = nb::cast<int>(t[0]);
        nb::tuple p = nb::cast<nb::tuple>(t[1]);
        l.position[0] = nb::cast<float>(p[0]);
        l.position[1] = nb::cast<float>(p[1]);
        l.position[2] = nb::cast<float>(p[2]);
        nb::tuple d = nb::cast<nb::tuple>(t[2]);
        l.direction[0] = nb::cast<float>(d[0]);
        l.direction[1] = nb::cast<float>(d[1]);
        l.direction[2] = nb::cast<float>(d[2]);
        nb::tuple c = nb::cast<nb::tuple>(t[3]);
        l.color[0] = nb::cast<float>(c[0]);
        l.color[1] = nb::cast<float>(c[1]);
        l.color[2] = nb::cast<float>(c[2]);
        l.intensity = nb::cast<float>(t[4]);
        l.range = nb::cast<float>(t[5]);
        l.inner_cos = nb::cast<float>(t[6]);
        l.outer_cos = nb::cast<float>(t[7]);
        out.push_back(l);
    }
    return out;
}

rome::ShadingParams make_shading(float ambient, float specular, float shininess) {
    rome::ShadingParams s{};
    s.ambient = ambient;
    s.specular = specular;
    s.shininess = shininess;
    return s;
}

/// Parse a Python list of (handle, (x,y,z), (rx,ry,rz), scale) into instances.
std::vector<rome::MeshInstance> parse_instances(const nb::list& instances) {
    std::vector<rome::MeshInstance> items;
    const std::size_t count = nb::len(instances);
    items.reserve(count);
    for (std::size_t i = 0; i < count; ++i) {
        nb::tuple entry = nb::cast<nb::tuple>(instances[i]);
        rome::MeshInstance mi{};
        mi.mesh = nb::cast<std::uint64_t>(entry[0]);
        nb::tuple p = nb::cast<nb::tuple>(entry[1]);
        mi.position[0] = nb::cast<float>(p[0]);
        mi.position[1] = nb::cast<float>(p[1]);
        mi.position[2] = nb::cast<float>(p[2]);
        nb::tuple r = nb::cast<nb::tuple>(entry[2]);
        mi.rotation[0] = nb::cast<float>(r[0]);
        mi.rotation[1] = nb::cast<float>(r[1]);
        mi.rotation[2] = nb::cast<float>(r[2]);
        mi.scale = nb::cast<float>(entry[3]);
        if (nb::len(entry) >= 5) {  // optional (r, g, b) colour
            nb::tuple c = nb::cast<nb::tuple>(entry[4]);
            mi.color[0] = nb::cast<float>(c[0]);
            mi.color[1] = nb::cast<float>(c[1]);
            mi.color[2] = nb::cast<float>(c[2]);
        }
        items.push_back(mi);
    }
    return items;
}

}  // namespace

NB_MODULE(_rome, m) {
    m.doc() = "Vulkan-backed 3D viewport primitives (native extension)";

    m.attr("__version__") = ROME_VERSION;

    // rome::Error surfaces in Python as rome.RomeError, so callers can catch
    // every failure from the renderer with one except clause.
    nb::exception<rome::Error>(m, "RomeError");

    nb::class_<rome::App>(m, "App", "A window with a Vulkan surface and a render loop.")
        .def(
            "__init__",
            [](rome::App* self, int width, int height, const std::string& title, bool vsync,
               bool resizable, bool validation, nb::object clear_color) {
                rome::AppConfig config{};
                config.window.width = width;
                config.window.height = height;
                config.window.title = title;
                config.window.resizable = resizable;
                config.vsync = vsync;
                config.validation = validation;
                if (!clear_color.is_none()) {
                    config.clear_color = color_from_tuple(nb::cast<nb::tuple>(clear_color));
                }
                new (self) rome::App(config);
            },
            "width"_a = 1280, "height"_a = 720, "title"_a = "ROME", "vsync"_a = true,
            "resizable"_a = true, "validation"_a = false, "clear_color"_a = nb::none())

        .def("tick", &rome::App::tick, nb::call_guard<nb::gil_scoped_release>(),
             "Process events and draw one frame. Returns False once closed.")
        .def("run", &rome::App::run, nb::call_guard<nb::gil_scoped_release>(),
             "Run the loop until the window closes.")

        .def(
            "upload_mesh",
            [](rome::App& self, const std::vector<float>& positions,
               const std::vector<float>& normals, const std::vector<std::uint32_t>& indices) {
                return self.upload_mesh(positions, normals, indices);
            },
            "positions"_a, "normals"_a, "indices"_a,
            "Upload a mesh (flat xyz positions and normals, triangle-list indices). "
            "Returns a handle to draw it with render_scene.")

        .def(
            "render_scene",
            [](rome::App& self, nb::list instances, std::tuple<float, float, float> cam_pos,
               std::tuple<float, float, float> cam_target, std::tuple<float, float, float> up,
               float fov, nb::list lights, float ambient, float specular, float shininess) {
                return self.render_scene(parse_instances(instances),
                                         make_camera(cam_pos, cam_target, up, fov),
                                         parse_lights(lights),
                                         make_shading(ambient, specular, shininess));
            },
            "instances"_a, "cam_pos"_a = std::make_tuple(0.0F, 0.0F, -5.0F),
            "cam_target"_a = std::make_tuple(0.0F, 0.0F, 0.0F),
            "up"_a = std::make_tuple(0.0F, 1.0F, 0.0F), "fov"_a = 50.0F, "lights"_a = nb::list(),
            "ambient"_a = 0.12F, "specular"_a = 0.4F, "shininess"_a = 32.0F,
            "Draw one frame of a scene. instances is a list of "
            "(handle, (x,y,z), (rx,ry,rz), scale, (r,g,b)); lights is a list of "
            "(type, pos, dir, color, intensity, range, inner_cos, outer_cos). "
            "Returns False once the window closes.")

        .def(
            "render_to_image",
            [](rome::App& self, nb::list instances, std::uint32_t width, std::uint32_t height,
               std::tuple<float, float, float> cam_pos, std::tuple<float, float, float> cam_target,
               std::tuple<float, float, float> up, float fov, nb::list lights, float ambient,
               float specular, float shininess) {
                std::vector<std::uint8_t> pixels = self.render_to_image(
                    width, height, parse_instances(instances),
                    make_camera(cam_pos, cam_target, up, fov), parse_lights(lights),
                    make_shading(ambient, specular, shininess));
                return nb::bytes(reinterpret_cast<const char*>(pixels.data()), pixels.size());
            },
            "instances"_a, "width"_a, "height"_a,
            "cam_pos"_a = std::make_tuple(0.0F, 0.0F, -5.0F),
            "cam_target"_a = std::make_tuple(0.0F, 0.0F, 0.0F),
            "up"_a = std::make_tuple(0.0F, 1.0F, 0.0F), "fov"_a = 50.0F, "lights"_a = nb::list(),
            "ambient"_a = 0.12F, "specular"_a = 0.4F, "shininess"_a = 32.0F,
            "Render a scene off-screen; returns width*height*4 RGBA8 bytes.")

        .def("set_title", &rome::App::set_title, "title"_a, "Set the window title text.")
        .def("keys_held", &rome::App::keys_held, "List of keys currently held down.")
        .def("take_pressed_keys", &rome::App::take_pressed_keys,
             "List of keys pressed since the last call (then cleared).")
        .def("set_mouse_look", &rome::App::set_mouse_look, "enabled"_a,
             "Capture the cursor and report relative motion, for mouse-look.")
        .def(
            "mouse_delta",
            [](rome::App& self) {
                const std::pair<float, float> d = self.mouse_delta();
                return nb::make_tuple(d.first, d.second);
            },
            "Mouse motion (dx, dy) since the last call, then reset.")

        .def("close", &rome::App::close, "Ask the loop to stop after this frame.")

        .def_prop_ro("running", &rome::App::is_running)
        .def_prop_ro("gpu_name", &rome::App::gpu_name)
        .def_prop_ro("frame_count", &rome::App::frame_count)
        .def_prop_ro("elapsed", &rome::App::elapsed)
        .def_prop_ro("delta_time", &rome::App::delta_time)
        .def_prop_ro("fps", &rome::App::fps)

        .def_prop_ro("size",
                     [](const rome::App& self) {
                         const rome::Extent2D extent = self.size();
                         return nb::make_tuple(extent.width, extent.height);
                     })

        .def_prop_rw(
            "clear_color", [](const rome::App& self) { return color_to_tuple(self.clear_color()); },
            [](rome::App& self, const nb::tuple& value) {
                self.set_clear_color(color_from_tuple(value));
            })

        // Context-manager support, so a viewport can be scoped with `with`.
        .def(
            "__enter__", [](rome::App& self) -> rome::App& { return self; },
            nb::rv_policy::reference_internal)
        .def("__exit__", [](rome::App& self, nb::handle, nb::handle, nb::handle) { self.close(); })

        .def("__repr__", [](const rome::App& self) {
            const rome::Extent2D extent = self.size();
            return "<rome.App " + std::to_string(extent.width) + "x" +
                   std::to_string(extent.height) + " on " + self.gpu_name() + ">";
        });
}
