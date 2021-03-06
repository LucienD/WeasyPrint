# coding: utf-8
"""
    weasyprint.layout.flex
    ------------------------

    Layout for flex containers and flex-items.

    :copyright: Copyright 2017 Lucien Deleu and contributors, see AUTHORS.
    :license: BSD, see LICENSE for details.

"""

from __future__ import division, unicode_literals

from math import log10

from ..css.properties import Dimension
from ..formatting_structure import boxes
from .percentages import resolve_percentages
from .preferred import max_content_width, min_content_width
from .tables import find_in_flow_baseline


class FlexLine(list):
    pass


def flex_layout(context, box, max_position_y, skip_stack, containing_block,
                device_size, page_is_empty, absolute_boxes, fixed_boxes):
    # Avoid a circular import
    from . import blocks

    resume_at = None

    # Step 1 is done in formatting_structure.boxes
    # Step 2
    if box.style['flex_direction'].startswith('row'):
        axis, cross = 'width', 'height'
    else:
        axis, cross = 'height', 'width'

    if box.style[axis] != 'auto':
        available_main_space = box.style[axis].value
    else:
        if axis == 'width':
            available_main_space = (
                containing_block.width -
                box.margin_left - box.margin_right -
                box.padding_left - box.padding_right -
                box.border_left_width - box.border_right_width)
        else:
            main_space = max_position_y - box.position_y
            if containing_block.height != 'auto':
                assert containing_block.height.unit == 'px'
                main_space = min(main_space, containing_block.height.value)
            available_main_space = (
                main_space -
                box.margin_top - box.margin_bottom -
                box.padding_top - box.padding_bottom -
                box.border_top_width - box.border_bottom_width)

    if box.style[cross] != 'auto':
        available_cross_space = box.style[cross].value
    else:
        if cross == 'height':
            main_space = max_position_y - box.content_box_y()
            if containing_block.height != 'auto':
                assert containing_block.height.unit == 'px'
                main_space = min(main_space, containing_block.height.value)
            available_cross_space = (
                main_space -
                box.margin_top - box.margin_bottom -
                box.padding_top - box.padding_bottom -
                box.border_top_width - box.border_bottom_width)
        else:
            available_cross_space = (
                containing_block.width -
                box.margin_left - box.margin_right -
                box.padding_left - box.padding_right -
                box.border_left_width - box.border_right_width)

    # Step 3
    children = box.children
    if skip_stack is not None:
        assert skip_stack[1] is None
        children = children[skip_stack[0]:]
    for child in children:
        if not child.is_flex_item:
            continue

        resolve_percentages(child, (0, 0))
        child.position_x = box.content_box_x()
        child.position_y = box.content_box_y()

        child.style = child.style.copy()
        resolve_percentages(box, containing_block)

        flex_basis = child.style['flex_basis']

        # "If a value would resolve to auto for width, it instead resolves
        # to content for flex-basis." Let's do this for height too.
        # See https://www.w3.org/TR/css-flexbox-1/#propdef-flex-basis
        if flex_basis == 'auto':
            if child.style[axis] == 'auto':
                flex_basis = 'content'
            else:
                flex_basis = child.style[axis]

        # Step 3.A
        # TODO: handle percentages
        if flex_basis != 'content':
            assert flex_basis.unit == 'px'
            child.flex_base_size = flex_basis.value

        # TODO: Step 3.B
        # TODO: Step 3.C

        # Step 3.D is useless, as we never have infinite sizes on paged media

        # Step 3.E
        else:
            if flex_basis == 'content':
                child.style[axis] = 'max-content'
            else:
                child.style[axis] = flex_basis

            # TODO: don't set style value, support *-content values instead
            if child.style[axis] == 'max-content':
                child.style[axis] = 'auto'
                if axis == 'width':
                    child.flex_base_size = max_content_width(context, child)
                else:
                    new_child = child.copy_with_children(child.children)
                    new_child.width = float('inf')
                    new_child = blocks.block_container_layout(
                        context, new_child, float('inf'), skip_stack,
                        device_size, page_is_empty, absolute_boxes,
                        fixed_boxes)[0]
                    child.flex_base_size = new_child.height
            elif child.style[axis] == 'min-content':
                child.style[axis] = 'auto'
                if axis == 'width':
                    child.flex_base_size = min_content_width(context, child)
                else:
                    new_child = child.copy_with_children(child.children)
                    new_child.width = 0
                    new_child = blocks.block_container_layout(
                        context, new_child, float('inf'), skip_stack,
                        device_size, page_is_empty, absolute_boxes,
                        fixed_boxes)[0]
                    child.flex_base_size = new_child.height
            else:
                assert child.style[axis].unit == 'px'
                child.flex_base_size = child.style[axis].value

        # TODO: the flex base size shouldn't take care of min and max sizes
        child.hypothetical_main_size = child.flex_base_size

    # Step 4
    if axis == 'width':
        blocks.block_level_width(box, containing_block)
    else:
        if box.style['height'] != 'auto':
            box.height = box.style['height'].value
        else:
            box.height = 0
            for i, child in enumerate(children):
                child_height = (
                    child.hypothetical_main_size +
                    child.border_top_width + child.border_bottom_width +
                    child.padding_top + child.padding_bottom)
                if child.margin_top != 'auto':
                    child_height += child.margin_top
                if child.margin_bottom != 'auto':
                    child_height += child.margin_bottom
                if child_height + box.height > main_space:
                    resume_at = (i, None)
                    children = children[:i]
                    break
                box.height += child_height

    # Step 5
    flex_lines = []

    line = []
    line_size = 0
    axis_size = getattr(box, axis)
    for child in sorted(children, key=lambda item: item.style['order']):
        if not child.is_flex_item:
            continue
        line_size += child.hypothetical_main_size
        if box.style['flex_wrap'] != 'nowrap' and line_size > axis_size:
            if line:
                flex_lines.append(FlexLine(line))
                line = [child]
                line_size = child.hypothetical_main_size
            else:
                line.append(child)
                flex_lines.append(FlexLine(line))
                line = []
                line_size = 0
        else:
            line.append(child)
    if line:
        flex_lines.append(FlexLine(line))

    # TODO: handle *-reverse using the terminology from the specification
    if box.style['flex_wrap'] == 'wrap-reverse':
        flex_lines.reverse()
    if box.style['flex_direction'].endswith('-reverse'):
        for line in flex_lines:
            line.reverse()

    # Step 6
    # See https://www.w3.org/TR/css-flexbox-1/#resolve-flexible-lengths
    for line in flex_lines:
        # Step 6.1
        hypothetical_main_size = sum(
            child.hypothetical_main_size for child in line)
        if hypothetical_main_size < available_main_space:
            flex_factor_type = 'grow'
        else:
            flex_factor_type = 'shrink'

        # Step 6.2
        for child in line:
            if flex_factor_type == 'grow':
                child.flex_factor = child.style['flex_grow']
            else:
                child.flex_factor = child.style['flex_shrink']
            if (child.flex_factor == 0 or
                    (flex_factor_type == 'grow' and
                        child.flex_base_size > child.hypothetical_main_size) or
                    (flex_factor_type == 'shrink' and
                        child.flex_base_size < child.hypothetical_main_size)):
                child.target_main_size = child.hypothetical_main_size
                child.frozen = True
            else:
                child.frozen = False

        # Step 6.3
        initial_free_space = available_main_space
        for child in line:
            if child.frozen:
                initial_free_space -= child.target_main_size
            else:
                initial_free_space -= child.flex_base_size

        # Step 6.4
        while not all(child.frozen for child in line):
            unfrozen_factor_sum = 0
            remaining_free_space = available_main_space

            # Step 6.4.b
            for child in line:
                if child.frozen:
                    remaining_free_space -= child.target_main_size
                else:
                    remaining_free_space -= child.flex_base_size
                    unfrozen_factor_sum += child.flex_factor

            if unfrozen_factor_sum < 1:
                initial_free_space *= unfrozen_factor_sum

            initial_magnitude = (
                int(log10(initial_free_space)) if initial_free_space > 0
                else -float('inf'))
            remaining_magnitude = (
                int(log10(remaining_free_space)) if initial_free_space > 0
                else -float('inf'))
            if initial_magnitude < remaining_magnitude:
                remaining_free_space = initial_free_space

            # Step 6.4.c
            if remaining_free_space == 0:
                # "Do nothing", but we at least set the flex_base_size as
                # target_main_size for next step.
                for child in line:
                    if not child.frozen:
                        child.target_main_size = child.flex_base_size
            else:
                scaled_flex_shrink_factors_sum = 0
                for child in line:
                    if not child.frozen:
                        child.scaled_flex_shrink_factor = (
                            child.flex_base_size * child.style['flex_shrink'])
                        scaled_flex_shrink_factors_sum += (
                            child.scaled_flex_shrink_factor)
                for child in line:
                    if not child.frozen:
                        if flex_factor_type == 'grow':
                            ratio = (
                                child.style['flex_grow'] /
                                scaled_flex_shrink_factors_sum)
                            child.target_main_size = (
                                child.flex_base_size +
                                remaining_free_space * ratio)
                        elif flex_factor_type == 'shrink':
                            ratio = (
                                child.scaled_flex_shrink_factor /
                                scaled_flex_shrink_factors_sum)
                            child.target_main_size = (
                                child.flex_base_size + remaining_free_space *
                                ratio)

            # Step 6.4.d
            # TODO: First part of this step is useless until 3.E is correct
            for child in line:
                child.adjustment = 0
                if not child.frozen and child.target_main_size < 0:
                    child.adjustment = -child.target_main_size
                    child.target_main_size = 0

            # Step 6.4.e
            adjustments = sum(child.adjustment for child in line)
            for child in line:
                if adjustments == 0:
                    child.frozen = True
                elif adjustments > 0 and child.adjustment > 0:
                    child.frozen = True
                elif adjustments < 0 and child.adjustment < 0:
                    child.frozen = True

        # Step 6.5
        for child in line:
            setattr(child, axis, child.target_main_size)

    # Step 7
    # TODO: fix TODO in build.flex_children
    # TODO: Handle breaks, skip_stack and resume_at instead of excluding Nones
    new_flex_lines = []
    for line in flex_lines:
        new_flex_line = FlexLine()
        for child in line:
            if cross == 'height':
                child = blocks.block_container_layout(
                    context, child,
                    available_cross_space + box.content_box_y(), skip_stack,
                    device_size, page_is_empty, absolute_boxes, fixed_boxes)[0]
            else:
                child.width = min_content_width(context, child, outer=False)
            if child is not None:
                new_flex_line.append(child)
        if new_flex_line:
            new_flex_lines.append(new_flex_line)
    flex_lines = new_flex_lines

    # Step 8
    cross_size = getattr(box, cross)
    if len(flex_lines) == 1 and cross_size != 'auto':
        flex_lines[0].cross_size = cross_size
    else:
        for line in flex_lines:
            collected_items = []
            not_collected_items = []
            for child in line:
                align_self = child.style['align_self']
                if (box.style['flex_direction'].startswith('row') and
                        align_self == 'baseline' and
                        child.margin_top != 'auto' and
                        child.margin_bottom != 'auto'):
                    collected_items.append(child)
                else:
                    not_collected_items.append(child)
            cross_start_distance = 0
            cross_end_distance = 0
            for child in collected_items:
                baseline = find_in_flow_baseline(child)
                if baseline is None:
                    baseline = 0
                else:
                    baseline -= child.position_y
                cross_start_distance = max(cross_start_distance, baseline)
                cross_end_distance = max(
                    cross_end_distance, child.margin_height() - baseline)
            collected_cross_size = cross_start_distance + cross_end_distance
            non_collected_cross_size = 0
            if not_collected_items:
                non_collected_cross_size = max(
                    child.margin_height() if cross == 'height'
                    else child.margin_width()
                    for child in not_collected_items)
            line.cross_size = max(
                collected_cross_size, non_collected_cross_size)
        # TODO: handle min/max height for single-line containers

    # Step 9
    if box.style['align_content'] == 'stretch':
        definite_cross_size = None
        if cross == 'height' and box.style['height'] != 'auto':
            definite_cross_size = box.style['height'].value
        elif cross == 'width':
            if isinstance(box, boxes.FlexBox):
                if box.style['width'] == 'auto':
                    definite_cross_size = available_cross_space
                else:
                    definite_cross_size = box.style['width'].value
        if definite_cross_size is not None:
            extra_cross_size = definite_cross_size - sum(
                line.cross_size for line in flex_lines)
            if extra_cross_size:
                for line in flex_lines:
                    line.cross_size += extra_cross_size / len(flex_lines)

    # TODO: Step 10

    # Step 11
    for line in flex_lines:
        for child in line:
            align_self = child.style['align_self']
            if align_self == 'auto':
                align_self = box.style['align_items']
            if align_self == 'stretch' and child.style[cross] == 'auto':
                cross_margins = (
                    (child.margin_top, child.margin_bottom)
                    if cross == 'height'
                    else (child.margin_left, child.margin_right))
                if child.style[cross] == 'auto':
                    if 'auto' not in cross_margins:
                        cross_size = line.cross_size
                        if cross == 'height':
                            cross_size -= (
                                child.margin_top + child.margin_bottom +
                                child.padding_top + child.padding_bottom +
                                child.border_top_width +
                                child.border_bottom_width)
                        else:
                            cross_size -= (
                                child.margin_left + child.margin_right +
                                child.padding_left + child.padding_right +
                                child.border_left_width +
                                child.border_right_width)
                        setattr(child, cross, cross_size)
                        # TODO: redo layout?
            # else: Cross size has been set by step 7

    # Step 12
    # TODO: handle rtl
    original_position_axis = (
        box.content_box_x() if axis == 'width'
        else box.content_box_y())
    justify_content = box.style['justify_content']
    if box.style['flex_direction'].endswith('-reverse'):
        if justify_content == 'flex-start':
            justify_content = 'flex-end'
        elif justify_content == 'flex-end':
            justify_content = 'flex-start'

    for line in flex_lines:
        position_axis = original_position_axis
        free_space = getattr(box, axis) - sum(
            child.margin_width() if axis == 'width'
            else child.margin_height() for child in line)

        if free_space > 0:
            margins = 0
            for child in line:
                if axis == 'width':
                    if child.margin_left == 'auto':
                        margins += 1
                    if child.margin_right == 'auto':
                        margins += 1
                else:
                    if child.margin_top == 'auto':
                        margins += 1
                    if child.margin_bottom == 'auto':
                        margins += 1
            if margins:
                free_space /= margins
                for child in line:
                    if axis == 'width':
                        if child.margin_left == 'auto':
                            child.margin_left = free_space
                        if child.margin_right == 'auto':
                            child.margin_right = free_space
                    else:
                        if child.margin_top == 'auto':
                            child.margin_top = free_space
                        if child.margin_bottom == 'auto':
                            child.margin_bottom = free_space
                free_space = 0

            if justify_content == 'flex-end':
                position_axis += free_space
            elif justify_content == 'center':
                position_axis += free_space / 2
            elif justify_content == 'space-around':
                position_axis += free_space / len(line) / 2

        for child in line:
            if axis == 'width':
                child.position_x = position_axis
            else:
                child.position_y = position_axis
            position_axis += (
                child.margin_width() if axis == 'width'
                else child.margin_height())
            if justify_content == 'space-around':
                position_axis += free_space / len(line)
            elif justify_content == 'space-between':
                if len(line) > 1:
                    position_axis += free_space / (len(line) - 1)

    # Step 13
    position_cross = (
        box.content_box_y() if cross == 'height'
        else box.content_box_x())
    for line in flex_lines:
        lower_baseline = 0
        # TODO: don't duplicate this loop
        for child in line:
            align_self = child.style['align_self']
            if align_self == 'auto':
                align_self = box.style['align_items']
            if align_self == 'baseline' and axis == 'width':
                # TODO: handle vertical text
                baseline = find_in_flow_baseline(child)
                if baseline is None:
                    # TODO: "If the item does not have a baseline in the
                    # necessary axis, then one is synthesized from the flex
                    # item’s border box."
                    child.baseline = 0
                else:
                    child.baseline = baseline - position_cross
                lower_baseline = max(lower_baseline, child.baseline)
        for child in line:
            cross_margins = (
                (child.margin_top, child.margin_bottom) if cross == 'height'
                else (child.margin_left, child.margin_right))
            auto_margins = sum([margin == 'auto' for margin in cross_margins])
            if auto_margins:
                # TODO: take care of margins insead of using margin_*()
                extra_cross = available_cross_space - (
                    child.margin_height() if cross == 'height'
                    else child.margin_width())
                if extra_cross > 0:
                    extra_cross /= auto_margins
                    if cross == 'height':
                        if child.margin_top == 'auto':
                            child.margin_top = extra_cross
                        if child.margin_bottom == 'auto':
                            child.margin_bottom = extra_cross
                    else:
                        if child.margin_left == 'auto':
                            child.margin_left = extra_cross
                        if child.margin_right == 'auto':
                            child.margin_right = extra_cross
                else:
                    if cross == 'height':
                        if child.margin_top == 'auto':
                            child.margin_top = 0
                        child.margin_bottom = extra_cross
                    else:
                        if child.margin_left == 'auto':
                            child.margin_left = 0
                        child.margin_right = extra_cross
            else:
                # Step 14
                align_self = child.style['align_self']
                if align_self == 'auto':
                    align_self = box.style['align_items']
                position = 'position_y' if cross == 'height' else 'position_x'
                setattr(child, position, position_cross)
                if align_self == 'flex-end':
                    if cross == 'height':
                        child.position_y += (
                            line.cross_size - child.margin_height())
                    else:
                        child.position_x += (
                            line.cross_size - child.margin_width())
                elif align_self == 'center':
                    if cross == 'height':
                        child.position_y += (
                            line.cross_size - child.margin_height()) / 2
                    else:
                        child.position_x += (
                            line.cross_size - child.margin_width()) / 2
                elif align_self == 'baseline':
                    if cross == 'height':
                        child.position_y += lower_baseline - child.baseline
                    else:
                        # Handle vertical text
                        pass
                elif align_self == 'stretch':
                    # TODO: take care of box-sizing
                    if child.style[cross] == 'auto':
                        if cross == 'height':
                            margins = (
                                child.margin_top + child.margin_bottom +
                                child.border_top_width +
                                child.border_bottom_width +
                                child.padding_top + child.padding_bottom)
                        else:
                            margins = (
                                child.margin_left + child.margin_right +
                                child.border_left_width +
                                child.border_right_width +
                                child.padding_left + child.padding_right)
                        # TODO: don't set style width, find a way to avoid
                        # width re-calculation after Step 16
                        child.style[cross] = Dimension(
                            line.cross_size - margins, 'px')
        position_cross += line.cross_size

    # Step 15
    if box.style[cross] == 'auto':
        # TODO: handle min-max
        setattr(box, cross, sum(line.cross_size for line in flex_lines))

    # Step 16
    elif len(flex_lines) > 1:
        extra_cross_size = getattr(box, cross) - sum(
            line.cross_size for line in flex_lines)
        direction = 'dy' if cross == 'height' else 'dx'
        if extra_cross_size > 0:
            cross_translate = 0
            for line in flex_lines:
                for child in line:
                    if child.is_flex_item:
                        child.translate(**{direction: cross_translate})
                        if box.style['align_content'] == 'flex-end':
                            child.translate(**{direction: extra_cross_size})
                        elif box.style['align_content'] == 'center':
                            child.translate(
                                **{direction: extra_cross_size / 2})
                        elif box.style['align_content'] == 'space-around':
                            child.translate(**{
                                direction: extra_cross_size /
                                len(flex_lines) / 2})
                if box.style['align_content'] == 'space-between':
                    cross_translate += extra_cross_size / (len(flex_lines) - 1)
                elif box.style['align_content'] == 'space-around':
                    cross_translate += extra_cross_size / len(flex_lines)

    # TODO: don't use block_level_layout, see TODOs in Step 14 and
    # build.flex_children.
    box = box.copy()
    box.children = []
    for line in flex_lines:
        for child in line:
            if child.is_flex_item:
                new_child = blocks.block_container_layout(
                    context, child, max_position_y, skip_stack, device_size,
                    page_is_empty, absolute_boxes, fixed_boxes)[0]
                if new_child is not None:
                    box.children.append(new_child)

    # TODO: check these returned values
    return box, resume_at, {'break': 'any', 'page': None}, [], False
