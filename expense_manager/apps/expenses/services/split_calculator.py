import re
from decimal import Decimal, ROUND_HALF_UP

class SplitCalculationError(Exception):
    pass

def round_half_up(val):
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    return val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def parse_split_details(details_str):
    """
    Parses a string like "Rohan 700; Priya 400; Meera 400" or
    "Aisha 30%; Rohan 30%; Priya 30%; Meera 20%" or "Aisha 1; Rohan 2; Priya 1; Dev 2".
    Returns a dict of {name: decimal_value}.
    """
    if not details_str:
        return {}
    
    results = {}
    # Split by semicolon
    items = details_str.split(';')
    for item in items:
        item = item.strip()
        if not item:
            continue
        
        # Split by last space (to handle names with spaces like "Priya S")
        parts = item.rsplit(None, 1)
        if len(parts) == 2:
            name, val_str = parts
            name = name.strip()
            # Remove any %, commas or quotes
            val_cleaned = re.sub(r'[%,"\']', '', val_str).strip()
            try:
                results[name] = Decimal(val_cleaned)
            except ValueError:
                raise SplitCalculationError(f"Could not parse split value '{val_str}' for participant '{name}'")
    return results

def calculate_splits(amount, split_type, participants, split_details_str=None):
    """
    Calculates the breakdown of splits.
    Returns a list of dicts: [
        {
            'participant': participant_obj,
            'share_amount': Decimal,
            'share_percentage': Decimal,
            'share_ratio': Decimal
        }
    ]
    """
    amount = Decimal(str(amount))
    if not participants:
        raise SplitCalculationError("No participants specified for split calculation.")

    num_participants = len(participants)
    results = []

    if split_type == 'EQUAL':
        # Split equally among all participants
        base_share = round_half_up(amount / Decimal(num_participants))
        # Account for rounding discrepancy
        shares = [base_share] * num_participants
        total_shares = sum(shares)
        diff = amount - total_shares
        
        if diff != 0:
            # Add difference to the first participant
            shares[0] += diff

        for idx, p in enumerate(participants):
            results.append({
                'participant': p,
                'share_amount': shares[idx],
                'share_percentage': round_half_up((shares[idx] / amount) * 100) if amount != 0 else Decimal('0.00'),
                'share_ratio': Decimal('1.00')
            })

    elif split_type == 'PERCENTAGE':
        details = parse_split_details(split_details_str)
        # Match participants by name
        participant_map = {p.name.lower(): p for p in participants}
        
        # Validate that we have split details for the participants
        pct_sum = Decimal('0.00')
        shares = {}
        
        for name, pct in details.items():
            normalized_name = name.lower()
            if normalized_name in participant_map:
                pct_sum += pct
                shares[normalized_name] = pct
            else:
                # User might specify split for someone not in group, but let's map them
                pass
                
        # If total percent sum != 100, we still calculate but we will flag validation error if requested
        # We calculate the absolute amount for each participant based on their percentage
        temp_amounts = {}
        for p in participants:
            pct = shares.get(p.name.lower(), Decimal('0.00'))
            # Calculate amount: (pct / 100) * amount
            temp_amounts[p.id] = round_half_up(amount * (pct / 100))

        # Adjust for rounding discrepancies if total percentage is 100%
        if pct_sum == 100:
            diff = amount - sum(temp_amounts.values())
            if diff != 0 and participants:
                temp_amounts[participants[0].id] += diff

        for p in participants:
            pct = shares.get(p.name.lower(), Decimal('0.00'))
            results.append({
                'participant': p,
                'share_amount': temp_amounts[p.id],
                'share_percentage': pct,
                'share_ratio': None
            })

    elif split_type == 'SHARES':
        details = parse_split_details(split_details_str)
        participant_map = {p.name.lower(): p for p in participants}
        
        total_ratios = Decimal('0.00')
        ratios = {}
        for p in participants:
            ratio = details.get(p.name.lower(), details.get(p.name, Decimal('0.00')))
            # Try matching with alias / name normalization
            if not ratio:
                # Find matching keys
                for k, v in details.items():
                    if k.lower() == p.name.lower():
                        ratio = v
                        break
            if not ratio:
                # Default to 0 or 1 if not specified? Let's treat as 0
                ratio = Decimal('0.00')
            ratios[p.id] = ratio
            total_ratios += ratio

        if total_ratios == 0:
            # If no ratios specified or sum is 0, split equally
            return calculate_splits(amount, 'EQUAL', participants)

        # Calculate exact amount per share
        temp_amounts = {}
        for p in participants:
            ratio = ratios[p.id]
            temp_amounts[p.id] = round_half_up(amount * (ratio / total_ratios))

        # Discrepancy check
        diff = amount - sum(temp_amounts.values())
        if diff != 0 and participants:
            # Find the participant with the largest non-zero ratio to adjust, or just the first
            non_zero_participants = [p for p in participants if ratios[p.id] > 0]
            target_p = non_zero_participants[0] if non_zero_participants else participants[0]
            temp_amounts[target_p.id] += diff

        for p in participants:
            results.append({
                'participant': p,
                'share_amount': temp_amounts[p.id],
                'share_percentage': round_half_up((temp_amounts[p.id] / amount) * 100) if amount != 0 else Decimal('0.00'),
                'share_ratio': ratios[p.id]
            })

    elif split_type == 'EXACT':
        details = parse_split_details(split_details_str)
        participant_map = {p.name.lower(): p for p in participants}

        temp_amounts = {}
        total_exact = Decimal('0.00')
        for p in participants:
            # Look up amount in details
            exact_val = Decimal('0.00')
            for name, val in details.items():
                if name.lower() == p.name.lower():
                    exact_val = val
                    break
            temp_amounts[p.id] = exact_val
            total_exact += exact_val
            
        # If there is a sum mismatch, we let the validator catch it, but we store the values as-is
        for p in participants:
            results.append({
                'participant': p,
                'share_amount': temp_amounts[p.id],
                'share_percentage': round_half_up((temp_amounts[p.id] / amount) * 100) if amount != 0 else Decimal('0.00'),
                'share_ratio': None
            })
            
    else:
        raise SplitCalculationError(f"Unsupported split type: {split_type}")

    return results
