def summarize_chip_yield(rows, required_items):
    chips = {}
    duplicates_ignored = 0
    missing_values = 0
    for row in rows:
        key = tuple(row.values())
        if key in chips:
            duplicates_ignored += 1
            continue
        chips[key] = True
        chip_id = row['chip_id']
        test_item = row['test_item']
        value = row['value']
        unit = row['unit']
        lower = float(row['lower'])
        upper = float(row['upper'])
        retest = int(row['retest'])
        if unit not in ('V', 'mV'):
            raise ValueError(f'Unknown unit: {unit}')
        if unit == 'mV':
            value = float(value) / 1000
        else:
            value = float(value)
        if value == '' or value < lower or value > upper:
            missing_values += 1
            continue
        if chip_id not in chips:
            chips[chip_id] = {}
        if test_item not in chips[chip_id]:
            chips[chip_id][test_item] = (retest, value)
        else:
            if chips[chip_id][test_item][0] == retest:
                if chips[chip_id][test_item][1] != value:
                    raise ValueError(f'Conflicting values for chip {chip_id}, test {test_item}, retest {retest}')
            elif chips[chip_id][test_item][0] < retest:
                chips[chip_id][test_item] = (retest, value)
    passed_chips = 0
    failed_chip_ids = []
    for chip_id, tests in chips.items():
        if chip_id == 'chip_id':
            continue
        if all(test in tests and lower <= tests[test][1] <= upper for test in required_items):
            passed_chips += 1
        else:
            failed_chip_ids.append(chip_id)
    failed_chip_ids.sort()
    total_chips = len(chips) - 1  # Subtract 1 to exclude the 'chip_id' key
    yield_value = passed_chips / total_chips if total_chips > 0 else 0.0
    return {
        'chips': total_chips,
        'passed_chips': passed_chips,
        'yield': round(yield_value, 4),
        'failed_chip_ids': failed_chip_ids,
        'duplicates_ignored': duplicates_ignored,
        'missing_values': missing_values
    }