#!/usr/bin/perl

use strict;
use warnings;

use DBI;
use Fcntl qw/:flock SEEK_END/;

require "./conf.pl";

our($db,$db_user,$db_pwd,$log_d,$doc_root,$upload_dir);

my %session;
my %auth_params;

my $id;
my $logd_in = 0;
my $authd = 0;
my $accountant = 0;

my $con;
my ($key,$iv,$cipher) = (undef, undef,undef);

if ( exists $ENV{"HTTP_SESSION"} ) {

	my @session_data = split/&/,$ENV{"HTTP_SESSION"};
	my @tuple;

	for my $unprocd_tuple (@session_data) {
		#came to learn (as often happens, purely by accident)
		#doing a split/=/,x= will give a list with a size of 1
		#desirable here (where it's OK to ignore unset vars)
		#would be awful where even a blank var means something (e.g
		#logging in with a blank password)
		@tuple = split/\=/,$unprocd_tuple;

		if (@tuple == 2) {
			$tuple[0] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$tuple[1] =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
			$session{$tuple[0]} = $tuple[1];		
		}
	}

	#logged in 
	if (exists $session{"id"}) {
		$logd_in++;
		$id = $session{"id"};
		#only bursar(user 2) can publish a fee structure 
		if ( $id eq "2" ) {

			$accountant++;
			if (exists $session{"sess_key"} ) {
				$con = DBI->connect("DBI:mysql:database=$db;host=localhost", $db_user, $db_pwd, {'RaiseError'=>1, 'AutoCommit'=> 0});

				use MIME::Base64 qw /decode_base64/;
				use Crypt::Rijndael;

				my $decoded = decode_base64($session{"sess_key"});
				my @decoded_bytes = unpack("C*", $decoded);

				my @sess_init_vec_bytes = splice(@decoded_bytes, 32);
				my @sess_key_bytes = @decoded_bytes;

				#read enc_keys_mem
				my $prep_stmt3 = $con->prepare("SELECT init_vec,aes_key FROM enc_keys_mem WHERE u_id=? LIMIT 1");

				if ( $prep_stmt3 ) {

					my $rc = $prep_stmt3->execute($id);

					if ( $rc ) {

						my ($mem_init_vec, $mem_aes_key) = (undef,undef);

						while (my @rslts = $prep_stmt3->fetchrow_array()) {
							$mem_init_vec = $rslts[0];
							$mem_aes_key = $rslts[1];
						}

						if ( defined $mem_init_vec ) {

							my @mem_init_vec_bytes = unpack("C*", $mem_init_vec);
							my @mem_aes_key_bytes = unpack("C*", $mem_aes_key);

							my ( @decrypted_init_vec, @decrypted_aes_key );

							for (my $i = 0; $i < @mem_init_vec_bytes; $i++) {
								$decrypted_init_vec[$i] = $mem_init_vec_bytes[$i] ^ $sess_init_vec_bytes[$i];
							}

							for (my $j = 0; $j < @mem_aes_key_bytes; $j++) {
								$decrypted_aes_key[$j] = $mem_aes_key_bytes[$j] ^ $sess_key_bytes[$j];
							}

							$key = pack("C*", @decrypted_aes_key);
							$iv = pack("C*", @decrypted_init_vec);

							$cipher = Crypt::Rijndael->new($key, Crypt::Rijndael::MODE_CBC());
							$cipher->set_iv($iv);

							$authd++;

						}
					}
					else {
						print STDERR "Couldn't execute SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
					}

				}
				else {
					print STDERR "Couldn't prepare SELECT FROM enc_keys_mem: ", $prep_stmt3->errstr, $/;
				}
			}
		}
	}
}

my $content = '';
my $feedback = '';
my $js = '';

my $header =
qq{
<iframe width="30%" height=80 frameborder="1" src="/welcome2.html">
		<h5>Welcome to the </br>Spanj Accounts Management Information System</h5>
	</iframe>
	<iframe width="20%" height=80 frameborder="1" src="/cgi-bin/check_login.cgi?cont=/">
	</iframe>
	<p><a href="/">Home</a> --&gt; <a href="/accounts/">Accounts</a> --&gt; <a href="/cgi-bin/cashbook.cgi">View Cashbook</a>
	<hr> 
};

unless ($authd) {
	if ($logd_in) {
		my $err = qq!<p><span style="color: red">Sorry, you do not have the appropriate privileges to view the cashbook.</span> Only the bursar and accountant(s) are authorized to take this action.!;

		#key issues?
		if ( $accountant ) {

			$err = qq!<p><span style="color: red">Sorry, could not obtain the encryption keys needed to manage accounts.</span> Try <a href="/cgi-bin/logout.cgi">logging out</a> and then log in again. If this problem persists, contact support.!;

		}

		$content .=
qq*
<!DOCTYPE html>
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::View Cashbook</title>
</head>
<body>
$header

</body>
</html> 
*;
		print "Status: 200 OK\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";

		my $len = length($content);
		print "Content-Length: $len\r\n";

		my @new_sess_array = ();

		for my $sess_key (keys %session) {
			push @new_sess_array, $sess_key."=".$session{$sess_key};        
		}
		my $new_sess = join ('&',@new_sess_array);

		print "X-Update-Session: $new_sess\r\n";

		print "\r\n";
		print $content;
		exit 0;
	}
	else {
		print "Status: 302 Moved Temporarily\r\n";
		print "Location: /login.html?cont=/cgi-bin/cashbook.cgi\r\n";
		print "Content-Type: text/html; charset=UTF-8\r\n";
       		my $res = 
qq!
<html lang="en">
<head>
<title>Spanj::Accounts Management Information System::View Cashbook</title>
</head>
<body>
$header
You should have been redirected to <a href="/login.html?cont=/cgi-bin/cashbook.cgi">/login.html?cont=/cgi-bin/cashbook.cgi</a>. If you were not, <a href="login.html?cont=/cgi-bin/cashbook.cgi">Click Here</a> 
</body>
</html>!;

		my $content_len = length($res);	
		print "Content-Length: $content_len\r\n";
		print "\r\n";
		print $res;
		exit 0;
	}
}

my $post_mode = 0;
my $boundary = undef;
my $multi_part = 0;

if (exists $ENV{"REQUEST_METHOD"} and uc($ENV{"REQUEST_METHOD"}) eq "POST") {
	

	if (exists $ENV{"CONTENT_TYPE"}) {
		if ($ENV{"CONTENT_TYPE"} =~ m!multipart/form-data;\sboundary=(.+)!i) {
			$boundary = $1;
			$multi_part++;
		}
	}

	unless ($multi_part) {
		my $str = "";

		while (<STDIN>) {
        	       	$str .= $_;
	       	}

		my $space = " ";
		$str =~ s/\x2B/$space/ge;
		my @auth_req = split/&/,$str;

		for my $auth_req_line (@auth_req) {
			my $eqs = index($auth_req_line, "=");	
			if ($eqs > 0) {
				my ($k, $v) = (substr($auth_req_line, 0, $eqs), substr($auth_req_line, $eqs + 1));
				$k =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$v =~ s/%([A-Fa-f0-9]{2})/chr(hex($1))/ge;
				$auth_params{$k} = $v;
			}
		}
	}
	#processing data sent 
	$post_mode++;
}

PM: {
if ( $post_mode ) {

	#valid,non-automated request
	if ( not exists $auth_params{"confirm_code"} or not exists $session{"confirm_code"} or $auth_params{"confirm_code"} ne $session{"confirm_code"} ) {
		$feedback = qq!<span style="color: red">Invalid tokens sent.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $spreadsheet_mode = 1;

	if ( exists $auth_params{"view_print"} ) {
		$spreadsheet_mode = 0;
	}

	my $show_sub_categories = 0;

	if ( exists $auth_params{"show_sub_categories"} and $auth_params{"show_sub_categories"} eq "1" ) {
		$show_sub_categories = 1;
	}

	
	unless ( exists $auth_params{"date_select"} ) {
		$feedback = qq!<span style="color: red">You did not specify the start and stop dates.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $date_select = $auth_params{"date_select"};

	unless ($date_select eq "today" or $date_select eq "this_week" or $date_select eq "this_month" or $date_select eq "this_fy" or $date_select eq "specific_dates") {
		$feedback = qq!<span style="color: red">You did not specify valid start and stop dates.</span>!;
		$post_mode = 0;
		last PM;
	}

	my $time = time;
	my $stop_time = $time;
	my $start_time = $time;

	my @today = localtime($time);

	if ($date_select eq "today") {
		my $substr_secs = ($today[2] * 3600) + ($today[1] * 60) + $today[0];
		$start_time -= $substr_secs;
	}

	elsif ($date_select eq "this_week") {
		my $substr_secs = ($today[2] * 3600) + ($today[1] * 60) + $today[0];
		my $wkday = $today[6];
		
		$wkday--;
		for (my $i = $wkday; $i >= 0; $i--) {
			$substr_secs += 86400;
		}
		$start_time -= $substr_secs;
	}

	elsif ($date_select eq "this_month") {
		my $substr_secs = ($today[2] * 3600) + ($today[1] * 60) + $today[0];
		my $mday = $today[3];
		
		$mday--;
		for ( my $i = $mday; $i > 0; $i-- ) {
			$substr_secs += 86400;
		}
		$start_time -= $substr_secs;
	}

	elsif ($date_select eq "this_fy") {

		my $substr_secs = ($today[2] * 3600) + ($today[1] * 60) + $today[0];
		my $yday = $today[7];
		
		$yday--;
		for ( my $i = $yday; $i >= 0; $i-- ) {
			$substr_secs += 86400;
		}
		$start_time -= $substr_secs;
	}

	elsif ( $date_select eq "specific_dates" ) {

		use Time::Local;
		my $current_yr = $today[5] + 1900;

		if (exists $auth_params{"start_date"} and $auth_params{"start_date"} =~ m!^([0-9]{1,2})/([0-9]{1,2})/([0-9]{2}(?:[0-9]{2})?)$! ) {

			my @start_date = ($1,$2 - 1,$3);

			if (length($start_date[2]) == 2) {
				my $current_century = substr($current_yr, 0, 2);
				$start_date[2] = $current_century . $start_date[2];
			}

			unless ($start_date[0] < 32 and $start_date[1] < 13 and $start_date[2] <= $current_yr) {
				$feedback = qq!<span style="color: red">You did not specify a valid start date.</span>!;
				$post_mode = 0;
				last PM;
			}

			if (exists $auth_params{"stop_date"} and $auth_params{"stop_date"} =~ m!^([0-9]{1,2})/([0-9]{1,2})/([0-9]{2}(?:[0-9]{2})?)$! ) {
				my @stop_date = ($1,$2 - 1,$3);

				if (length($stop_date[2]) == 2) {
					my $current_century = substr($current_yr, 0, 2);
					$stop_date[2] = $current_century . $stop_date[2];
				}

				unless ($stop_date[0] < 32 and $stop_date[1] < 13 and $stop_date[2] <= $current_yr) {
					$feedback = qq!<span style="color: red">You did not specify a valid stop date.</span>!;
					$post_mode = 0;
					last PM;
				}
			
				$start_time = timelocal(0,0,0,@start_date);
				$stop_time = timelocal(59,59,23,@stop_date);

				#reversed dates
				if ( $stop_time < $start_time ) {
					my $tmp = $stop_time;
					$stop_time = $start_time;
					$start_time = $tmp;
				}

				if ( $start_time < 0 or $stop_time < 0 or $start_time > $time or $stop_time > $time ) {
					$feedback = qq!<span style="color: red">You did not specify valid start and stop dates.</span>!;
					$post_mode = 0;
					last PM;
				}
			}
		}
		else {
			$feedback = qq!<span style="color: red">You did not specify valid start and stop dates.</span>!;
			$post_mode = 0;
			last PM;
		}
	}

	use Digest::HMAC_SHA1 qw/hmac_sha1_hex/;

	#read current budget
	my %votehead_lookup = ();
	my %votehead_hierarchy = ();
	my %child_lookup = ();

	$votehead_hierarchy{"arrears"} = {"arrears" => "Arrears"};
	$votehead_lookup{"arrears"} = "Arrears";

	my $has_children = 0;

	my $prep_stmt2 = $con->prepare("SELECT votehead,votehead_parent,amount,hmac FROM budget");
	
	if ( $prep_stmt2 ) {

		my $rc = $prep_stmt2->execute();
		
		if ( $rc ) {

			while (my @rslts = $prep_stmt2->fetchrow_array()) {		

				my $decrypted_votehead = $cipher->decrypt( $rslts[0] );
				my $votehead = remove_padding($decrypted_votehead);
	
				my $decrypted_votehead_parent = $cipher->decrypt( $rslts[1] );
				my $votehead_parent = remove_padding($decrypted_votehead_parent);

				my $decrypted_amnt = $cipher->decrypt( $rslts[2] );	
				my $amnt = remove_padding($decrypted_amnt);
	
				#valid decryption	
				if ( $amnt =~ /^\d+(\.\d{1,2})?$/ ) {
					#check HMAC
					my $hmac = uc(hmac_sha1_hex($votehead . $votehead_parent . $amnt, $key));	
					if ( $hmac eq $rslts[3] ) {
						#did this to enable even parents
						#to record their budget amounts 
						if ( $votehead_parent eq "" ) {
							$votehead_parent = $votehead;
						}
						else {
							$has_children++;
							$child_lookup{lc($votehead)} = lc($votehead_parent);
						}

						${$votehead_hierarchy{lc($votehead_parent)}}{lc($votehead)} = $votehead;
						$votehead_lookup{lc($votehead)} = $votehead;
					}
				}
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM budget:", $prep_stmt2->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM budget:", $prep_stmt2->errstr, $/;
	}	

	my %votehead_totals;
	my $entry_cntr = 0;
	my %entries = ();

	my %receipt_no_lookup = ();
	#read cashbook
	my $prep_stmt3 = $con->prepare("SELECT receipt_votehead,votehead,amount,time,hmac FROM cash_book");

	if ($prep_stmt3) {

		my $rc = $prep_stmt3->execute();

		if ($rc) {

			while ( my @rslts = $prep_stmt3->fetchrow_array() ) {

				my $receipt_votehead = remove_padding($cipher->decrypt($rslts[0]));
				my $votehead = remove_padding($cipher->decrypt($rslts[1]));
				my $amount = remove_padding($cipher->decrypt($rslts[2]));
				my $time = remove_padding($cipher->decrypt($rslts[3]));

				#allow negative amounts to handle overpayments as a credit
				if ( $amount =~ /^\-?\d+(\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($receipt_votehead . $votehead . $amount . $time, $key));
	
					if ( $hmac eq $rslts[4] ) {
						#within our search range
						if ( $time >= $start_time and $time <= $stop_time ) {

							my @time_then = localtime($time);
							my $day_month_yr = sprintf("%02d/%02d/%d", $time_then[3], $time_then[4] + 1, $time_then[5] + 1900);

							my $rcpt_no = "";
							if ( $receipt_votehead =~ /^(\d+)\-/ ) {
								$rcpt_no = $1;
								$receipt_no_lookup{$rcpt_no} = "";
							}
							elsif ( $receipt_votehead =~ /^(Prepayment\(\d+)-\d+\)\-/) {
								$rcpt_no = $1 . ")";
								$receipt_no_lookup{$rcpt_no} = "";
							}
							elsif ( $receipt_votehead =~ /^Update\((\d+)-\d+\)\-/) {
								#print "X-Debug-$1: seen update with value $amount\r\n";
								$rcpt_no = "Fee Update($1)";
								$receipt_no_lookup{$rcpt_no} = $1;
							}

							
							my $dr_cr_prefix = "dr_";

							#my $votehead_n = $votehead_lookup{$votehead};
							if ($amount >= 0) {
								$entries{$entry_cntr++} = {"date" => $day_month_yr, "time" => $time, "particulars" => $rcpt_no, "votehead" => $votehead, "amount" => $amount, "dr_cr" => 1};
							}
							else {
								$dr_cr_prefix = "cr_";
								$amount *= -1;
								$entries{$entry_cntr++} = {"date" => $day_month_yr, "time" => $time, "particulars" => $rcpt_no, "votehead" => $votehead, "amount" => $amount, "dr_cr" => 1.25};
							}

							if ($show_sub_categories) {
								$votehead_totals{$dr_cr_prefix . $votehead} += $amount;
							}
							else {
								my $parent = $votehead;
								if (exists $child_lookup{$votehead}) {
									$parent = $child_lookup{$votehead};
								}
								$votehead_totals{$dr_cr_prefix . $parent} += $amount; 
							}
						}
					}	
				}	
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM cash_book:", $prep_stmt3->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM cash_book:", $prep_stmt3->errstr, $/;
	}

	my $prep_stmt1 = $con->prepare("SELECT receipt_no,paid_in_by,class,amount,mode_payment,ref_id,votehead,time,hmac FROM receipts WHERE receipt_no=? LIMIT 1");	
	
	if ( $prep_stmt1 ) {

		for my $receipt (keys %receipt_no_lookup) {
			#Update(xx) already knows its owner
			next unless ( $receipt_no_lookup{$receipt} eq "" );

			my $receipt_no = undef;
			my $rc = $prep_stmt1->execute($receipt);

			if ($rc) {

				while (my @rslts = $prep_stmt1->fetchrow_array() ) {

					$receipt_no = $rslts[0];
					my $paid_in_by = remove_padding($cipher->decrypt($rslts[1]));
					my $class = remove_padding($cipher->decrypt($rslts[2]));
					my $amount = remove_padding($cipher->decrypt($rslts[3]));
					my $mode_payment = remove_padding($cipher->decrypt($rslts[4]));
					my $ref_id = remove_padding($cipher->decrypt($rslts[5]));
					my $votehead = remove_padding($cipher->decrypt($rslts[6]));
					my $time = remove_padding($cipher->decrypt($rslts[7]));

					if ( $amount =~ /^\d+(\.\d{1,2})?$/ ) {	
						#check HMAC
						my $hmac = uc(hmac_sha1_hex($paid_in_by . $class . $amount . $mode_payment . $ref_id . $votehead . $time, $key));	
						if ( $hmac eq $rslts[8] ) {

							$receipt_no_lookup{$receipt} = $paid_in_by;
						}
					}
				}

			}
			else {
				print STDERR "Couldn't execute SELECT FROM receipts: ", $prep_stmt1->errstr, $/;
			}
			delete $receipt_no_lookup{$receipt} if (not defined $receipt_no);
		}

	}
	else {
		print STDERR "Couldn't prepare SELECT FROM receipts: ", $prep_stmt1->errstr, $/;
	}

	my %voucher_no_lookup = ();
	my $prep_stmt4 = $con->prepare("SELECT voucher_votehead,votehead,amount,time,hmac FROM payments_book");

	if ($prep_stmt4) {
					
		my $rc = $prep_stmt4->execute();

		if ($rc) {

			while ( my @rslts = $prep_stmt4->fetchrow_array() ) {

				my $voucher_votehead = remove_padding($cipher->decrypt($rslts[0]));
				my $votehead = remove_padding($cipher->decrypt($rslts[1]));
				my $amount = remove_padding($cipher->decrypt($rslts[2]));
				my $time = remove_padding($cipher->decrypt($rslts[3]));
				
				my $voucher_no = $voucher_votehead;
				$voucher_no =~ s/\-$votehead//;

				#Special voucher for fee updates
				if ($voucher_no =~ /^Update\((\d+)-\d+\)/) {
					$voucher_no = "Fee Update($1)";
					$voucher_no_lookup{$voucher_no} = {"paid_out_to" => $1, "ref_id" => ""};
				}

				if ( $amount =~ /^\d+(?:\.\d{1,2})?$/ ) {

					my $hmac = uc(hmac_sha1_hex($voucher_votehead . $votehead . $amount . $time , $key));

					if ( $hmac eq $rslts[4] ) {


						if ( $time >= $start_time and $time <= $stop_time ) {

							my @time_then = localtime($time);
							my $day_month_yr = sprintf("%02d/%02d/%d", $time_then[3], $time_then[4] + 1, $time_then[5] + 1900);

							#my $votehead_n = $votehead_lookup{$votehead};
							$entries{$entry_cntr++} = { "date" => $day_month_yr, "time" => $time, "particulars" => $voucher_no, "votehead" => $votehead, "amount" => $amount, "dr_cr" => 2 };
							$voucher_no_lookup{$voucher_no} = {} unless (exists $voucher_no_lookup{$voucher_no}->{"paid_out_to"});

							my $dr_cr_prefix = "cr_";
							if ($show_sub_categories) {
								$votehead_totals{$dr_cr_prefix . $votehead} += $amount;
							}
							else {
								my $parent = $votehead;
								if (exists $child_lookup{$votehead}) {
									$parent = $child_lookup{$votehead};
								}
								$votehead_totals{$dr_cr_prefix . $parent} += $amount; 
							}
						}
					}

				}
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM payments_book:", $prep_stmt4->errstr, $/;
		}

	}
	else {
		print STDERR "Couldn't prepare SELECT FROM payment_book:", $prep_stmt4->errstr, $/;
	}
	
	#read payment vouchers
	my $prep_stmt5 = $con->prepare("SELECT voucher_no,paid_out_to,amount,mode_payment,ref_id,description,votehead,time,hmac FROM payment_vouchers WHERE voucher_no=? LIMIT 1");

	if ($prep_stmt5) {

		for my $voucher ( keys %voucher_no_lookup ) {
			next if (exists $voucher_no_lookup{$voucher}->{"paid_out_to"});
			my $voucher_no = undef;

			my $rc = $prep_stmt5->execute($voucher);

			if ( $rc ) {
	
				while ( my @rslts = $prep_stmt5->fetchrow_array() ) {

					$voucher_no = $rslts[0];
					my $paid_out_to = remove_padding($cipher->decrypt($rslts[1]));
					my $amount = remove_padding($cipher->decrypt($rslts[2]));
					my $mode_payment = remove_padding($cipher->decrypt($rslts[3]));
					my $ref_id = remove_padding($cipher->decrypt($rslts[4]));
					my $descr = remove_padding($cipher->decrypt($rslts[5]));
					my $votehead = remove_padding($cipher->decrypt($rslts[6]));
					my $time = remove_padding($cipher->decrypt($rslts[7]));

					if ( $amount =~ /^\d+(\.\d{1,2})?$/ ) {
	
						my $hmac = uc(hmac_sha1_hex($paid_out_to . $amount . $mode_payment . $ref_id . $descr . $votehead . $time, $key));

						if ( $hmac eq $rslts[8] ) {
							
							$voucher_no_lookup{$voucher} = { "paid_out_to" => $paid_out_to, "ref_id" => $ref_id };
						}
					}
				}
			}
			else {
				print STDERR "Couldn't prepare SELECT FROM payment_vouchers:", $prep_stmt5->errstr, $/;
			}

			delete $voucher_no_lookup{$voucher} if (not defined $voucher_no);
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM payment_vouchers:", $prep_stmt5->errstr, $/;
	}

	#Opening/Closing Balances
	my %opening_balances;
	my %closing_balances;

	my %bank_accounts = ();

	my $prep_stmt0 = $con->prepare("SELECT value FROM vars WHERE id='2-bank accounts' LIMIT 1");

	if ($prep_stmt0) {

		my $rc = $prep_stmt0->execute();
		if ($rc) {
			while ( my @rslts = $prep_stmt0->fetchrow_array() ) {

				my @bank_accnts = split/,/,$rslts[0];

				foreach ( @bank_accnts ) {
					$bank_accounts{lc($_)} = {"name" => $_, "balance" => 0};
				}
			}
		}
		else {
			print STDERR "Couldn't execute SELECT FROM vars: ", $prep_stmt0->errstr, $/;
		}
	}
	else {
		print STDERR "Couldn't prepare SELECT FROM vars: ", $prep_stmt0->errstr, $/;
	}



	if ( scalar(keys %bank_accounts) > 0 ) {

		my $prep_stmt1 = $con->prepare("SELECT bank_account,amount,time,action_type,hmac FROM bank_actions WHERE BINARY bank_account=?");

		if ($prep_stmt1) {

			for my $bank_account (keys %bank_accounts) {

				#this lc() is complicating a simple task
				my $accnt = ${$bank_accounts{$bank_account}}{"name"};
				#need to slurp to mem to sort by time 
				my %actions = ();
				my $enc_bank_account = $cipher->encrypt(add_padding($accnt));

				my $rc = $prep_stmt1->execute($enc_bank_account);
				if ($rc) {
					my $cntr = 0;

					while ( my @rslts = $prep_stmt1->fetchrow_array() ) {

						my $accnt = remove_padding($cipher->decrypt($rslts[0]));
						my $amount = remove_padding($cipher->decrypt($rslts[1]));
						my $time = remove_padding($cipher->decrypt($rslts[2]));
						my $action_type = remove_padding($cipher->decrypt($rslts[3]));
						
						#valid decryption
						if ( $amount =~ /^\d{1,10}(\.\d{1,2})?$/ ) {

							my $hmac = uc(hmac_sha1_hex($accnt . $amount . $time . $action_type, $key));

							#auth the data
							if ( $hmac eq $rslts[4] ) {
								$actions{$cntr++} = {"amount" => $amount, "time" => $time, "action_type" => $action_type};
								
							}
						}
					}

					foreach (sort { ${$actions{$a}}{"time"} <=> ${$actions{$b}}{"time"} } keys %actions ) {

						#avoid multiple de-refs later
						my $action_time = ${$actions{$_}}{"time"};
						

						#break out if these events concern
						#times past our timeframe of interest
						last if ($action_time > $stop_time);

						my $action_type = ${$actions{$_}}{"action_type"};	

						if ($action_type  eq "3" ) {
							${$bank_accounts{$bank_account}}{"balance"} = ${$actions{$_}}{"amount"};
						}
						#withdrawal
						elsif ( $action_type eq "2" ) {
							${$bank_accounts{$bank_account}}{"balance"} -= ${$actions{$_}}{"amount"};
						}
						#deposit
						elsif ( $action_type eq "1" ) {
							${$bank_accounts{$bank_account}}{"balance"} += ${$actions{$_}}{"amount"};
						}

						

						#print qq!X-Debug-$_: seen accnt alt[$action_type] for $bank_account(${$actions{$_}}{"amount"}) new balance is ${$bank_accounts{$bank_account}}{"balance"}\r\n!;

						#aggregating all events before our start time 
						#to determine the init state
						if ( $action_time <= $start_time ) {
							$opening_balances{$accnt} = ${$bank_accounts{$bank_account}}{"balance"};	
						}

						if ( $action_time >= $start_time ) {

							#only record withdrawal & deposits
							if ( $action_type eq "2" or $action_type eq "1" ) {

								my @time_then = localtime($action_time);
								my $day_month_yr = sprintf("%02d/%02d/%d", $time_then[3], $time_then[4] + 1, $time_then[5] + 1900);

								my $action_descr = $action_type eq "1" ? "Bank Deposit" : "Bank Withdrawal";
								$action_descr .= "[$accnt]";

								#my $votehead_n = $votehead_lookup{$votehead};
								$entries{$entry_cntr++} = { "date" => $day_month_yr, "time" => $action_time, "particulars" => $action_descr, "votehead" => "to/from bank", "amount" => ${$actions{$_}}{"amount"}, "dr_cr" => 3};	
							}

						}
					}

					#broken out/fallen out
					#if not set opening_balances
					#set it now
					if ( not exists $opening_balances{$accnt} ) {
						$opening_balances{$accnt} = ${$bank_accounts{$bank_account}}{"balance"};
					}
					#the state of the bank_accounts
					#is the closing balances
					$closing_balances{$accnt} = ${$bank_accounts{$bank_account}}{"balance"};
					#print qq!X-Debug: $accnt set closing balance to $closing_balances{$accnt}\r\n!;
				}

				else {
					print STDERR "Couldn't execute SELECT FROM bank_actions: ", $prep_stmt0->errstr, $/;
				}
			}
		}
		else {
			print STDERR "Couldn't prepare SELECT FROM bank_actions:", $prep_stmt0->errstr, $/;
		}

	}


	if ($spreadsheet_mode) {
		use Spreadsheet::WriteExcel;
		use Spreadsheet::WriteExcel::Utility;

		my ($workbook,$worksheet,$dr_worksheet,$cr_worksheet,$bold,$bold_2,$bold_3,$rotated,$default_props,$spreadsheet_name,$row,$col,$dr_row,$dr_col,$cr_row,$cr_col) = (undef,undef,undef,undef,undef,undef,undef,undef,undef,undef,0,0,0,0,0,0);

		$workbook = Spreadsheet::WriteExcel->new("${doc_root}/accounts/cashbooks/${start_time}.xls");

		if (defined $workbook) {

			$bold = $workbook->add_format( ("bold" => 1, "size" => 12) );
			$bold_2 = $workbook->add_format( ("bold" => 1, "size" => 13) );
			$bold_3 = $workbook->add_format( ("bold" => 1, "size" => 14) );

			$rotated = $workbook->add_format( ("bold" => 1, "size" => 13, "align" => "left", "rotation"=>"90") );
			my $rotated_2 = $workbook->add_format( ("bold" => 1, "size" => 12, "align" => "left", "rotation"=>"90"));

			$default_props = $workbook->add_format( ("size" => 12) );

			my %merge_props = ("valign" => "vcenter", "align" => "center", "bold" => 1, "size" => 14);
			my $merge_format = $workbook->add_format(%merge_props);

			$merge_props{"size"} = 13;
			$merge_props{"rotation"} = 90;
			my $merge_format_2 = $workbook->add_format(%merge_props);

			$workbook->set_properties( ("title" => "Cash Book", "comments" => "lecxEetirW::teehsdaerpS htiw detaerC; User: $id") );
			$worksheet = $workbook->add_worksheet("Merged");
			$worksheet->set_landscape();
			$worksheet->hide_gridlines(0);

			$dr_worksheet = $workbook->add_worksheet("Debits");
			$dr_worksheet->set_landscape();
			$dr_worksheet->hide_gridlines(0);

			$cr_worksheet = $workbook->add_worksheet("Credits");
			$cr_worksheet->set_landscape();
			$cr_worksheet->hide_gridlines(0);

			#write opening balances
			if ( scalar(keys %opening_balances) > 0 ) {

				for my $accnt (keys %opening_balances) {
					$worksheet->write_string($row,0, $accnt, $bold);
					$worksheet->write_number($row,1,$opening_balances{$accnt}, $default_props);				
					$row++;

					$dr_worksheet->write_string($dr_row,0, $accnt, $bold);
					$dr_worksheet->write_number($dr_row,1,$opening_balances{$accnt}, $default_props);				
					$dr_row++;

					$cr_worksheet->write_string($cr_row,0, $accnt, $bold);
					$cr_worksheet->write_number($cr_row,1,$opening_balances{$accnt}, $default_props);				
					$cr_row++;

				}

			}

			
			my $top_rowstop = 1;

			if ($show_sub_categories and $has_children) {
				$top_rowstop = 2;
			}

			#Date
			$worksheet->merge_range($row, 0, $row + $top_rowstop, 0, "Date", $merge_format);
			$dr_worksheet->merge_range($dr_row, 0, $dr_row + $top_rowstop, 0, "Date", $merge_format);
			$cr_worksheet->merge_range($cr_row, 0, $cr_row + $top_rowstop, 0, "Date", $merge_format);

			#Partculars|To/From Whom
			$worksheet->merge_range($row, 1, $row + $top_rowstop, 1, "To/From Whom", $merge_format);
			$dr_worksheet->merge_range($dr_row, 1, $dr_row + $top_rowstop, 1, "From Whom Received", $merge_format);
			$cr_worksheet->merge_range($cr_row, 1, $cr_row + $top_rowstop, 1, "To Whom Paid", $merge_format);


			#Voucher|Receipt No.
			$worksheet->merge_range($row, 2, $row + $top_rowstop, 2, "Voucher/Receipt No.", $merge_format);
			$dr_worksheet->merge_range($dr_row, 2, $dr_row + $top_rowstop, 2, "Receipt No.", $merge_format);
			$cr_worksheet->merge_range($cr_row, 2, $cr_row + $top_rowstop, 2, "Voucher No.", $merge_format);

			#Cheque No.
			$worksheet->merge_range($row, 3, $row + $top_rowstop, 3, "Cheque No.", $merge_format);
			#dr has no cheque no.--all payments are received as cash	
			$cr_worksheet->merge_range($cr_row, 3, $cr_row + $top_rowstop, 3, "Cheque No.", $merge_format);

			#Cash
			$worksheet->merge_range($row, 4, $row + $top_rowstop, 4, "Cash", $merge_format);
			$dr_worksheet->merge_range($dr_row, 3, $dr_row + $top_rowstop, 3, "Cash", $merge_format);
			$cr_worksheet->merge_range($cr_row, 4, $cr_row + $top_rowstop, 4, "Cash", $merge_format);

			#Bank
			$worksheet->merge_range($row, 5, $row + $top_rowstop, 5, "Bank", $merge_format);
			$dr_worksheet->merge_range($dr_row, 4, $dr_row + $top_rowstop, 4, "Bank", $merge_format);
			$cr_worksheet->merge_range($cr_row, 5, $cr_row + $top_rowstop, 5, "Bank", $merge_format);

			#Total
			$worksheet->merge_range($row, 6, $row + $top_rowstop, 6, "Total", $merge_format);
			$dr_worksheet->merge_range($dr_row, 5, $dr_row + $top_rowstop, 5, "Total", $merge_format);
			$cr_worksheet->merge_range($cr_row, 6, $cr_row + $top_rowstop, 6, "Total", $merge_format);


			my $num_voteheads = scalar(keys %votehead_hierarchy);

			if ( $show_sub_categories ) {
				$num_voteheads = scalar(keys %votehead_lookup);
			}

			#Debit
			$worksheet->merge_range($row, 7, $row, (6 + $num_voteheads + 1) -1, "Debit", $merge_format);
			$dr_worksheet->merge_range($row, 6, $row, (5 + $num_voteheads + 1) -1, "Debit", $merge_format);
			#Credit
			$worksheet->merge_range($row, 6+$num_voteheads + 1, $row, (6 + ($num_voteheads * 2) + 1) - 1, "Credit", $merge_format);
			$cr_worksheet->merge_range($row, 7, $row, (6 + $num_voteheads + 1) -1, "Credit", $merge_format);

			$row++;
			$dr_row++;
			$cr_row++;

			$col = 7;
			$dr_col = 6;
			$cr_col = 7;

			for my $dr_cr ("Debit", "Credit") {

				for my $votehead ( sort { $a cmp $b } keys %votehead_hierarchy ) {

					my $votehead_n = $votehead_lookup{$votehead};
					my $num_children = scalar(keys %{$votehead_hierarchy{$votehead}});

					if ($show_sub_categories and $has_children) {	
						if ($num_children > 1) {
							$worksheet->merge_range($row, $col, $row, ($col + $num_children) - 1, $votehead_n, $merge_format_2);
							$col += $num_children;

							#Debits
							if ($dr_cr eq "Debit") {
								$dr_worksheet->merge_range($dr_row, $dr_col, $dr_row, ($dr_col + $num_children) - 1, $votehead_n, $merge_format_2);
								$dr_col += $num_children;
							}
							#Credits
							else {
								$cr_worksheet->merge_range($cr_row, $cr_col, $cr_row, ($cr_col + $num_children) - 1, $votehead_n, $merge_format_2);
								$cr_col += $num_children;
							}
						
						}
						else {
							$worksheet->merge_range($row, $col, $row + 1, $col, $votehead_n, $merge_format_2);
							#Debit
							if ($dr_cr eq "Debit") {
								$dr_worksheet->merge_range($dr_row, $dr_col, $dr_row + 1, $dr_col, $votehead_n, $merge_format_2);
								$dr_col++;
							}
							#Credit
							else {
								$cr_worksheet->merge_range($cr_row, $cr_col, $cr_row + 1, $cr_col, $votehead_n, $merge_format_2);
								$cr_col++;
							}
							$col++;
						}
					}
					else {
						$worksheet->write_string($row, $col++, $votehead_n, $rotated);
						#Debit
						if ($dr_cr eq "Debit") {
							$dr_worksheet->write_string($dr_row, $dr_col++, $votehead_n, $rotated);
						}
						#Credit
						else {
							$cr_worksheet->write_string($cr_row, $cr_col++, $votehead_n, $rotated);
						}
					}
				}

				#To/From Bank
				if ($show_sub_categories and $has_children) {
					#$worksheet->merge_range($row, $col, $row + 1, $col, "To/From Bank", $merge_format_2);
					#$col++;
				}
				else {
					#$worksheet->write_string($row, $col++, "To/From Bank", $rotated);
				}
			}

			if ( $show_sub_categories and $has_children) {

				$row++;
				$col = 7;

				$dr_row++;
				$dr_col = 6;
				
				$cr_row++;
				$cr_col = 7;

				for my $dr_cr ("Debit", "Credit") {

					for my $votehead ( sort { $a cmp $b } keys %votehead_hierarchy ) {

						my $num_children = scalar(keys %{$votehead_hierarchy{$votehead}});

						if ($num_children  > 1 ) {

							for my $child (sort {$a cmp $b} keys %{$votehead_hierarchy{$votehead}} ) {
	
								my $votehead_n = $votehead_lookup{$child};
								$worksheet->write_string($row,$col++,$votehead_n,$rotated_2);
	
								#Debit
								if ( $dr_cr eq "Debit") {
									$dr_worksheet->write_string($dr_row,$dr_col++,$votehead_n,$rotated_2);
								}
								#Credit
								else {
									$cr_worksheet->write_string($cr_row,$cr_col++,$votehead_n,$rotated_2);
								}
							}
						}
						else {
							$col++;
							if ($dr_cr eq "Debit") {
								$dr_col++;
							}
							else {
								$cr_col++;
							}
						}
					}
					#$col++;
				}
			}
	
			
		
			my $data_start = $row;

			my %ordered_voteheads = ();	
			my $votehead_cntr = 0;
			#sort order does matter
			for my $votehead (sort {$a cmp $b} keys %votehead_hierarchy ) {

				if ( $show_sub_categories ) {
					foreach (sort {$a cmp $b} keys %{$votehead_hierarchy{$votehead}} ) {	
						$ordered_voteheads{$_} = $votehead_cntr++;
					}
				}
				else {	
					$ordered_voteheads{$votehead} =$votehead_cntr++;
				}
			}

			my @sorted_entries = sort { $entries{$a}->{"time"} <=> $entries{$b}->{"time"} } keys %entries;
	
			for ( my $i = 0; $i < scalar(@sorted_entries); $i++ ) {

				#could have been deleted by a look-forward
				next if ( not exists $entries{$sorted_entries[$i]} );

				my %row_votehead_vals = ();

				my $max = $entries{$sorted_entries[$i]}->{"particulars"};
				my $min = $max;

				my $dr_cr = $entries{$sorted_entries[$i]}->{"dr_cr"};

				my $date = $entries{$sorted_entries[$i]}->{"date"};
				my $votehead = $entries{$sorted_entries[$i]}->{"votehead"};

				if ($dr_cr < 3) {

					unless ( $show_sub_categories ) {
						if (exists $child_lookup{$votehead}) {
							$votehead = $child_lookup{$votehead};	
						}
					}
					$row_votehead_vals{$votehead} += $entries{$sorted_entries[$i]}->{"amount"};	
				}

				my $row_total = $entries{$sorted_entries[$i]}->{"amount"};

				#trying to avoid doing arithmetic on
				#non-numeric bank action descriptions
				if ($dr_cr < 3) {

					#look forward for birds of a feather
					for ( my $j = $i+1; $j < scalar(@sorted_entries); $j++ ) {

						next if ( not exists $entries{$sorted_entries[$j]} );
						#break out if past current date
						last unless ($entries{$sorted_entries[$j]}->{"date"} eq $date);

						#don't coalsce vouchers		
						if ($dr_cr == 2) {
							last unless ($entries{$sorted_entries[$i]}->{"particulars"} eq $entries{$sorted_entries[$j]}->{"particulars"});
						}

						#must be same dr/cr as entry being processed
						my $walk_forward_dr = $entries{$sorted_entries[$j]}->{"dr_cr"};	

						next unless ( $walk_forward_dr eq $dr_cr );

						my $particulars = $entries{$sorted_entries[$j]}->{"particulars"};	

						#better be a number
						#but then this' perl
						if ($particulars =~ /^\d+$/){
							if ( $particulars > $max ) {
								$max = $particulars;
							}
							elsif ( $particulars < $min) {
								$min = $particulars;
							}
						}
						else {
							if ( $particulars gt $max ) {
								$max = $particulars;
							}
							elsif ( $particulars lt $min) {
								$min = $particulars;
							}
						}

						my $amnt = $entries{$sorted_entries[$j]}->{"amount"};
						my $vothead = $entries{$sorted_entries[$j]}->{"votehead"};	

						unless ( $show_sub_categories ) {

							if (exists $child_lookup{$vothead}) {
								$vothead = $child_lookup{$vothead};
							}
						}
		
						$row_votehead_vals{$vothead} += $amnt;
						$row_total += $amnt;

						#remove this entry
						delete $entries{$sorted_entries[$j]};
					}

				}

				my $particulars_descr = "";
				if ($max eq $min) {
					$particulars_descr .= " $min";
				}
				else {
					$particulars_descr .= " $min-$max";
				}
			
				if ($dr_cr == 3) {
					$particulars_descr = $max;
				}

	
				my $to_from_whom = "";

				#Debits	
				if ($dr_cr == 1 or $dr_cr == 1.25) {

					my $prepayment_prefix = "";
					$prepayment_prefix = "Prepayment " if ($dr_cr == 1.25);

					if (exists $receipt_no_lookup{$min}) {
						my $from_min = $receipt_no_lookup{$min};
						$to_from_whom .= "$prepayment_prefix$from_min";
						if ($min ne $max) {
							if (exists $receipt_no_lookup{$max}) {
								my $from_max = $receipt_no_lookup{$max};
								$to_from_whom .= "-$from_max";
							}
						}
					}

				}

				#Credits
				if ($dr_cr == 2) {	
					if (exists $voucher_no_lookup{$min}) {
						$to_from_whom = $voucher_no_lookup{$min}->{"paid_out_to"};
					}
				}


				#Bank
				if ($dr_cr == 3) {
					$to_from_whom = $max;
				}
	
				$row++;
				$col = 7;

				$dr_col = 6;	
				$cr_col = 7;

				$worksheet->write_string($row, 0, $date, $default_props);
				$worksheet->write_string($row, 1, $to_from_whom, $default_props);
				$worksheet->write_string($row, 2, $particulars_descr, $default_props);

				if ($dr_cr == 1 or $dr_cr == 3) {
					$dr_row++;
					$dr_worksheet->write_string($dr_row, 0, $date, $default_props);
					$dr_worksheet->write_string($dr_row, 1, $to_from_whom, $default_props);
					$dr_worksheet->write_string($dr_row, 2, $particulars_descr, $default_props);

					if ($dr_cr == 1) {
						$dr_worksheet->write_number($dr_row,3,$row_total,$default_props);
						$dr_worksheet->write_blank($dr_row,4, $default_props);
						$dr_worksheet->write_number($dr_row,5,$row_total,$default_props);

						$worksheet->write_blank($row,3, $default_props);
						$worksheet->write_number($row,4,$row_total,$default_props);
						$worksheet->write_blank($row,5, $default_props);
						$worksheet->write_number($row,6,$row_total,$default_props);
					}
					else {
						$dr_worksheet->write_blank($dr_row,3, $default_props);
						$dr_worksheet->write_number($dr_row,4,$row_total,$default_props);
						$dr_worksheet->write_number($dr_row,5,$row_total,$default_props);

						$worksheet->write_blank($row,3, $default_props);
						$worksheet->write_blank($row,4, $default_props);
						$worksheet->write_number($row,5,$row_total,$default_props);
						$worksheet->write_number($row,6,$row_total,$default_props);
					}
					
				
				}
				#not elsif to allow bank actions to be double-entered
				if ($dr_cr == 1.25 or $dr_cr == 2 or $dr_cr == 3) {
					$cr_row++;
					$cr_worksheet->write_string($cr_row, 0, $date, $default_props);
					$cr_worksheet->write_string($cr_row, 1, $to_from_whom, $default_props);
					$cr_worksheet->write_string($cr_row, 2, $particulars_descr, $default_props);

					#prepayments, no cheque
					if ($dr_cr == 1.25) {
						$cr_worksheet->write_blank($cr_row, 3, $default_props);
						$cr_worksheet->write_number($cr_row,4,$row_total,$default_props);
						$cr_worksheet->write_blank($cr_row, 5, $default_props);
						$cr_worksheet->write_number($cr_row,6,$row_total,$default_props);

						$worksheet->write_blank($row, 3, $default_props);
						$worksheet->write_number($row,4,$row_total,$default_props);
						$worksheet->write_blank($row, 5, $default_props);
						$worksheet->write_number($row,6,$row_total,$default_props);
					}
					#payment vouchers; possibly via Cheque no., if any
					elsif ($dr_cr == 2) {

						my $ref_id = $voucher_no_lookup{$min}->{"ref_id"};	
				
						#perhaps cash
						if ($ref_id eq "") {
							$cr_worksheet->write_blank($cr_row, 3, $default_props);
							$cr_worksheet->write_number($cr_row,4,$row_total,$default_props);
							$cr_worksheet->write_blank($cr_row, 5, $default_props);
							$cr_worksheet->write_number($cr_row,6,$row_total,$default_props);

							$worksheet->write_blank($row, 3, $default_props);
							$worksheet->write_number($row,4,$row_total,$default_props);
							$worksheet->write_blank($row, 5, $default_props);
							$worksheet->write_number($row,6,$row_total,$default_props);
						}
						#bank
						else {
							$cr_worksheet->write_string($cr_row, 3, $ref_id, $default_props);
							$cr_worksheet->write_blank($cr_row, 4, $default_props);
							$cr_worksheet->write_number($cr_row,5,$row_total,$default_props);
							$cr_worksheet->write_number($cr_row,6,$row_total,$default_props);

							$worksheet->write_string($row, 3, $ref_id, $default_props);
							$worksheet->write_blank($row, 4, $default_props);
							$worksheet->write_number($row,5,$row_total,$default_props);
							$worksheet->write_number($row,6,$row_total,$default_props);
						}
					}
					#Bank actions, no cheque
					else {
						$cr_worksheet->write_blank($cr_row, 3, $default_props);
						$cr_worksheet->write_blank($cr_row, 4, $default_props);
						$cr_worksheet->write_number($cr_row,5,$row_total,$default_props);
						$cr_worksheet->write_number($cr_row,6,$row_total,$default_props);

						$worksheet->write_blank($row, 3, $default_props);
						$worksheet->write_blank($row, 4, $default_props);
						$worksheet->write_number($row,5,$row_total,$default_props);
						$worksheet->write_number($row,6,$row_total,$default_props);
					}
				
				}

				#take a (simpler|different) approach from
				#the one I take for the HTML table
				#was hard enough visualizing HTML tables
				#don't want to visualize this spreadsheet

				#debits
				if ($dr_cr == 1 or $dr_cr == 3) {
					#write data; then blanks
					for my $vthead (sort {$ordered_voteheads{$a} <=> $ordered_voteheads{$b} } keys %ordered_voteheads) {
				
						if ( exists $row_votehead_vals{$vthead} ) {
							$worksheet->write_number($row,$col++,$row_votehead_vals{$vthead},$default_props);
							$dr_worksheet->write_number($dr_row,$dr_col++,$row_votehead_vals{$vthead},$default_props);
						}
						else {
							$worksheet->write_blank($row,$col++,$default_props);
							$dr_worksheet->write_blank($dr_row,$dr_col++,$default_props);
						}
						
					}
					$dr_row++;
					#one blank for To/From Bank
					#$worksheet->write_blank($row,$col++,$default_props);
					#a string of blanks for the credits
					foreach (keys %ordered_voteheads) {
						$worksheet->write_blank($row,$col++,$default_props);
					}

					#one more blank for To/From Bank
					#$worksheet->write_blank($row,$col++,$default_props);
				}

				#credits
				if ($dr_cr == 2 or $dr_cr == 1.25 or $dr_cr == 3) {
					#a string of blanks for the debits
					foreach (keys %ordered_voteheads) {
						$worksheet->write_blank($row,$col++,$default_props);	
					}

					#one blank for To/From Bank
					#$worksheet->write_blank($row,$col++,$default_props);

					for my $vthead (sort {$ordered_voteheads{$a} <=> $ordered_voteheads{$b} } keys %ordered_voteheads) {
				
						if ( exists $row_votehead_vals{$vthead} ) {
							$worksheet->write_number($row,$col++,$row_votehead_vals{$vthead},$default_props);
							$cr_worksheet->write_number($cr_row,$cr_col++,$row_votehead_vals{$vthead},$default_props);
						}
						else {
							$worksheet->write_blank($row,$col++,$default_props);
							$cr_worksheet->write_blank($cr_row,$cr_col++,$default_props);
						}
					}
					$cr_row++;
					#one more blank for To/From Bank
					#$worksheet->write_blank($row,$col++,$default_props);
				}
				#bank actions
				#no need for this in this new dispensation
=pod
				elsif ($dr_cr == 3) {

					my $amnt = $entries{$sorted_entries[$i]}->{"amount"};

					#a string of blanks for the debits
					foreach (keys %ordered_voteheads) {
						$worksheet->write_blank($row,$col++,$default_props);
					}

					#To/From Bank
					$worksheet->write_number($row,$col++,$amnt,$default_props);

					#a string of blanks for the credits
					foreach (keys %ordered_voteheads) {
						$worksheet->write_blank($row,$col++,$default_props);
					}

					#To/From Bank
					#$worksheet->write_number($row,$col++,$amnt,$default_props);

				}
=cut
				$row++;
			}

			$col = 0;
			$dr_col = 0;
			$cr_col = 0;

			#votehead totals
			$worksheet->write_blank($row,$col++,$bold);
			$worksheet->write_blank($row,$col++,$bold);
			$worksheet->write_blank($row,$col++,$bold);
			$worksheet->write_blank($row,$col++,$bold);
			$worksheet->write_blank($row,$col++,$bold);
			$worksheet->write_blank($row,$col++,$bold);
			$worksheet->write_blank($row,$col++,$bold);	

			$dr_worksheet->write_blank($dr_row,$dr_col++,$bold);
			$dr_worksheet->write_blank($dr_row,$dr_col++,$bold);
			$dr_worksheet->write_blank($dr_row,$dr_col++,$bold);
			$dr_worksheet->write_blank($dr_row,$dr_col++,$bold);
			$dr_worksheet->write_blank($dr_row,$dr_col++,$bold);
			$dr_worksheet->write_blank($dr_row,$dr_col++,$bold);
			$dr_worksheet->write_blank($dr_row,$dr_col++,$bold);

			$cr_worksheet->write_blank($cr_row,$cr_col++,$bold);
			$cr_worksheet->write_blank($cr_row,$cr_col++,$bold);
			$cr_worksheet->write_blank($cr_row,$cr_col++,$bold);
			$cr_worksheet->write_blank($cr_row,$cr_col++,$bold);
			$cr_worksheet->write_blank($cr_row,$cr_col++,$bold);
			$cr_worksheet->write_blank($cr_row,$cr_col++,$bold);
			$cr_worksheet->write_blank($cr_row,$cr_col++,$bold);

			$col = 7;
			$dr_col = 6;
			$cr_col = 7;

			for my $dr_or_cr ("dr_", "cr_") {

				for my $vthead (sort {$ordered_voteheads{$a} <=> $ordered_voteheads{$b} } keys %ordered_voteheads) {
					if ( exists $votehead_totals{$dr_or_cr . $vthead} ) {
						$worksheet->write_number($row,$col++,$votehead_totals{$dr_or_cr . $vthead}, $bold);
						if ($dr_or_cr eq "dr_") {
							$dr_worksheet->write_number($dr_row,$dr_col++,$votehead_totals{$dr_or_cr . $vthead}, $bold);
						}
						else {
							$cr_worksheet->write_number($cr_row,$cr_col++,$votehead_totals{$dr_or_cr . $vthead}, $bold);
						}
					}
					else {
						$worksheet->write_blank($row,$col++,$bold);
						if ($dr_or_cr eq "dr_") {
							$dr_worksheet->write_blank($dr_row,$dr_col++,$bold);
						}
						else {
							$cr_worksheet->write_blank($cr_row,$cr_col++,$bold);
						}
					}
				}

				if ($dr_or_cr eq "dr_") {
					$dr_row++;
				}
				else {
					$cr_row++;
				}
				#$worksheet->write_blank($row,$col++,$bold);
			}		

			$row++;
			$dr_row++;
			$cr_row++;

			#write closing balances
			if ( scalar(keys %closing_balances) > 0 ) {
				for my $accnt (keys %closing_balances) {
					$worksheet->write_string($row,0, $accnt, $bold);
					$worksheet->write_number($row,1,$closing_balances{$accnt}, $default_props);	
					$row++;
	
					$dr_worksheet->write_string($dr_row,0, $accnt, $bold);
					$dr_worksheet->write_number($dr_row,1,$closing_balances{$accnt}, $default_props);	
					$dr_row++;

					$cr_worksheet->write_string($cr_row,0, $accnt, $bold);
					$cr_worksheet->write_number($cr_row,1,$closing_balances{$accnt}, $default_props);	
					$cr_row++;
				} 
			}

			$workbook->close();

			print "Status: 302 Moved Temporarily\r\n";
			print "Location: /accounts/cashbooks/${start_time}.xls\r\n";
			print "Content-Type: text/html; charset=UTF-8\r\n";

   			my $content = 
qq!
<html>
<head>
<title>Spanj: Accounts Management Information System - Redirect Failed</title>
</head>
<body>
You should have been redirected to <a href="/accounts/cashbooks/${start_time}.xls">/accounts/cashbooks/${start_time}.xls</a>. If you were not, <a href="/accounts/cashbooks/${start_time}.xls">Click here</a> 
</body>
</html>
!;


			my $content_len = length($content);	
			print "Content-Length: $content_len\r\n";
			print "\r\n";
			print $content;
			if ($con) {
				$con->disconnect();
			}

			#log download
			my @today = localtime;	
			my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

			open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
      	 		if ($log_f) {

				my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
				flock ($log_f, LOCK_EX) or print STDERR "Could not log download cashbook for $id due to flock error: $!$/";
				seek ($log_f, 0, SEEK_END);	
 
				print $log_f "$id DOWNLOAD CASHBOOK $time\n";
				flock ($log_f, LOCK_UN);
               			close $log_f;
      		  	}
			else {
				print STDERR "Could not log download cashbook $id: $!\n";
			}

			exit 0;	
		}
		else {
			print STDERR "Could not create workbook: $!$/";	
		}	
	}
	else {

		my $dr_top_rowspan = "6";
		my $cr_top_rowspan = "7";
		my $top_rowspan = "2";
	
		if ($show_sub_categories and $has_children) {
			$top_rowspan = "3";
		}

		my $num_voteheads = scalar(keys %votehead_hierarchy) + 1;

		if ($show_sub_categories) {
			$num_voteheads = scalar(keys %votehead_lookup) + 1;
		}

		my $dr_table = qq!<TABLE border="1" cellspacing="5%" cellpadding="5%">!;
		my $cr_table = qq!<TABLE border="1" cellspacing="5%" cellpadding="5%">!;;

		$dr_table .= qq!<thead><tr style="font-size: 1.4em"><th rowspan="$dr_top_rowspan">Date<th rowspan="$dr_top_rowspan">From Whom Received<th rowspan="$dr_top_rowspan">Receipt No.<th rowspan="$dr_top_rowspan">Cash<th rowspan="$dr_top_rowspan">Bank<th rowspan="$dr_top_rowspan">Total<th colspan="$num_voteheads">Debit!;

		$cr_table .= qq!<thead><tr style="font-size: 1.4em"><th rowspan="$cr_top_rowspan">Date<th rowspan="$cr_top_rowspan">To Whom Paid<th rowspan="$cr_top_rowspan">Voucher No.<th rowspan="$cr_top_rowspan">Cheque No.<th rowspan="$cr_top_rowspan">Cash<th rowspan="$cr_top_rowspan">Bank<th rowspan="$cr_top_rowspan">Total<th colspan="$num_voteheads">Credit!;

		#my $table_header = qq!<thead><tr style="font-size: 1.4em"><th rowspan="$top_rowspan">Date<th rowspan="$top_rowspan">Particulars<th colspan="$num_voteheads">Debit<th colspan="$num_voteheads">Credit!;

		$dr_table .= qq!<tr style="font-size: 1.2em">!;
		$cr_table .= qq!<tr style="font-size: 1.2em">!;

		#$table_header .= qq!<tr style="font-size: 1.2em">!;
	
		for my $dr_cr ("Debit", "Credit") {
		
			for my $votehead ( sort { $a cmp $b } keys %votehead_hierarchy ) {

				my $colspan = "1";
				my $rowspan = "1";

				if ($show_sub_categories and $has_children) {
					$rowspan = "2";
				}

				my $num_children = scalar(keys %{$votehead_hierarchy{$votehead}});

				if ( $num_children > 1 ) {
					$colspan = $num_children;
					$rowspan = "1";
				}

				my $votehead_n = $votehead_lookup{$votehead};

				#$table_header .= qq!<th class="rotate" colspan="$colspan" rowspan="$rowspan"><div><span>$votehead_n</span></div>!;
				$dr_table .= qq!<th class="rotate" colspan="$colspan" rowspan="$rowspan"><div><span>$votehead_n</span></div>! if ($dr_cr eq "Debit");
				$cr_table .= qq!<th class="rotate" colspan="$colspan" rowspan="$rowspan"><div><span>$votehead_n</span></div>! if ($dr_cr eq "Credit");

			}

			my $rowspan = "1";

			if ($show_sub_categories and $has_children) {
				$rowspan = "2";
			}

			#$table_header .= qq!<th class="rotate" colspan="1" rowspan="$rowspan"><div><span>To/From Bank</span></div>!;	
		}

		if ($show_sub_categories and $has_children ) {
	
			#$table_header .= qq!<tr style="font-size: 1em">!;
			$dr_table .= qq!<tr style="font-size: 1em">!;
			$cr_table .= qq!<tr style="font-size: 1em">!;

			for my $dr_or_cr ("Debit", "Credit") {

				for my $votehead ( sort { $a cmp $b } keys %votehead_hierarchy ) {

					if ( scalar(keys %{$votehead_hierarchy{$votehead}}) > 1 ) {

						for my $child (sort {$a cmp $b} keys %{$votehead_hierarchy{$votehead}} ) {
	
							my $votehead_n = $votehead_lookup{$child};

							#$table_header .= qq!<th class="rotate"><div><span>$votehead_n</span></div></th>!; 
							$dr_table .= qq!<th class="rotate"><div><span>$votehead_n</span></div></th>! if ( $dr_or_cr eq "Debit" );
							$cr_table .= qq!<th class="rotate"><div><span>$votehead_n</span></div></th>! if ( $dr_or_cr eq "Credit" );
						}
					}
				}

			}

		}

		#$table_header .= "</thead>";
		$dr_table .= "</thead>";
		$cr_table .= "</thead>";

		#my $tbody = "<tbody>";

		$dr_table .= "<tbody>";
		$cr_table .= "<tbody>";

		my $blank_entries = "";

		my %ordered_voteheads = ();	
		my $votehead_cntr = 0;
		#sort order does matter
		for my $votehead (sort {$a cmp $b} keys %votehead_hierarchy ) {

			if ( $show_sub_categories ) {
				foreach (sort {$a cmp $b} keys %{$votehead_hierarchy{$votehead}} ) {
					$blank_entries .= "<TD>&nbsp;";
					$ordered_voteheads{$_} = $votehead_cntr++;
				}
			}
			else {
				$blank_entries .= "<TD>&nbsp;";
				$ordered_voteheads{$votehead} =$votehead_cntr++;
			}
		}

		my @sorted_entries = sort { $entries{$a}->{"time"} <=> $entries{$b}->{"time"} } keys %entries;
	
		for ( my $i = 0; $i < scalar(@sorted_entries); $i++ ) {

			#could have been deleted by a look-forward
			next if ( not exists $entries{$sorted_entries[$i]} );

			my %row_votehead_vals = ();

			my $max = $entries{$sorted_entries[$i]}->{"particulars"};
			my $min = $max;

			my $dr_cr = $entries{$sorted_entries[$i]}->{"dr_cr"};

			my $date = $entries{$sorted_entries[$i]}->{"date"};
			my $votehead = $entries{$sorted_entries[$i]}->{"votehead"};

			my $row_total = $entries{$sorted_entries[$i]}->{"amount"};

			if ($dr_cr < 3) {

				unless ( $show_sub_categories ) {
					if (exists $child_lookup{$votehead}) {
						$votehead = $child_lookup{$votehead};	
					}
				}
				$row_votehead_vals{$votehead} += $entries{$sorted_entries[$i]}->{"amount"};	
			}

			#trying to avoid doing arithmetic on
			#non-numeric bank action descriptions
			
			if ($dr_cr < 3) {

				#look forward for birds of a feather
				for ( my $j = $i+1; $j < scalar(@sorted_entries); $j++ ) {

					next if ( not exists $entries{$sorted_entries[$j]} );
					
					#don't coalsce vouchers		
					if ($dr_cr == 2) {
						last unless ($entries{$sorted_entries[$i]}->{"particulars"} eq $entries{$sorted_entries[$j]}->{"particulars"});
					}
					#break out if past current date
					last unless ($entries{$sorted_entries[$j]}->{"date"} eq $date);

					#must be same dr/cr as entry being processed
					my $walk_forward_dr = $entries{$sorted_entries[$j]}->{"dr_cr"};	

					next unless ( $walk_forward_dr eq $dr_cr );

					my $particulars = $entries{$sorted_entries[$j]}->{"particulars"};	

					#better be a number
					#but then this' perl
					if ($particulars =~ /^\d+$/){

						if ( $particulars > $max ) {
							$max = $particulars;
						}
						elsif ( $particulars < $min) {
							$min = $particulars;
						}

					}
					else {
						if ( $particulars gt $max ) {
							$max = $particulars;
						}
						elsif ( $particulars lt $min) {
							$min = $particulars;
						}
					}

					my $amnt = $entries{$sorted_entries[$j]}->{"amount"};
					my $vothead = $entries{$sorted_entries[$j]}->{"votehead"};	

					unless ( $show_sub_categories ) {

						if (exists $child_lookup{$vothead}) {
							$vothead = $child_lookup{$vothead};
						}
					}
		
					$row_votehead_vals{$vothead} += $amnt;
					$row_total += $amnt;

					#remove this entry
					delete $entries{$sorted_entries[$j]};
				}

			}

			my $particulars_descr = "";
			if ($max eq $min) {
				$particulars_descr .= " $min";
			}
			else {
				$particulars_descr .= " $min-$max";
			}
			
			if ($dr_cr == 3) {
				$particulars_descr = $max;
			}

			if ($dr_cr == 1.25) {
				$particulars_descr = "Rcpt(s) $particulars_descr";
			}

			my $to_from_whom = "";

			#Debits	
			if ($dr_cr == 1 or $dr_cr == 1.25) {
				if (exists $receipt_no_lookup{$min}) {

					my $from_min = $receipt_no_lookup{$min};
					$to_from_whom .= "$from_min";

					if ($min ne $max) {
						if (exists $receipt_no_lookup{$max}) {
							my $from_max = $receipt_no_lookup{$max};
							$to_from_whom .= "-$from_max";
						}
					}
				}
			}

			#Credits
			if ($dr_cr == 2) {	
				if (exists $voucher_no_lookup{$min}) {
					$to_from_whom = $voucher_no_lookup{$min}->{"paid_out_to"};
				}
			}


			#Bank
			if ($dr_cr == 3) {
				$to_from_whom = $max;
			}

			my $f_row_total = format_currency($row_total);
			#Debits
			if ($dr_cr == 1) {
				
				$dr_table .= "<TR><TD>$date<TD>$to_from_whom<TD>$particulars_descr<TD>$f_row_total<TD>&nbsp;<TD>$f_row_total";
			}

			#Prepayments
			if ($dr_cr == 1.25) {
				$cr_table .= "<TR><TD>$date<TD>Prepayment $to_from_whom<TD>$particulars_descr<TD>&nbsp;<TD>$f_row_total<TD>&nbsp;<TD>$f_row_total";
			}

			#Credits
			if ($dr_cr == 2 ) {

				my $ref_id = $voucher_no_lookup{$min}->{"ref_id"};
				my ($cash,$bank) = ("&nbsp;", $f_row_total);
				
				if ($ref_id eq "") {
					$ref_id = "&nbsp;";
					$cash = $f_row_total;
					$bank = "&nbsp;";
				}
				
				$cr_table .= "<TR><TD>$date<TD>$to_from_whom<TD>$min<TD>$ref_id<TD>$cash<TD>$bank<TD>$f_row_total";

			}

			#Bank Actions
			if ($dr_cr == 3) {
				$dr_table .= "<TR><TD>$date<TD>$to_from_whom<TD>&nbsp;<TD>&nbsp;<TD>$f_row_total<TD>$f_row_total";
				$cr_table .= "<TR><TD>$date<TD>$to_from_whom<TD>&nbsp;<TD>&nbsp;<TD>&nbsp;<TD>$f_row_total<TD>$f_row_total";
			}

			#$tbody .= "<TR><TD>$date<TD>$particulars_descr";

			my $to_from_bank = "&nbsp;";

			if ( $dr_cr == 3 ) {
				$to_from_bank = format_currency($entries{$sorted_entries[$i]}->{"amount"});
			}
=pod
			#prepend debits
			if ( $dr_cr == 2 or $dr_cr == 1.25 or $dr_cr == 3 ) {
				#add an extra cell for to/from bank
				#$tbody .= $blank_entries;
				#$tbody .= "<TD>$to_from_bank";
			}

			#data
			if ($dr_cr < 3) {
				for my $vthead (sort {$ordered_voteheads{$a} <=> $ordered_voteheads{$b} } keys %ordered_voteheads) {
				
					if ( exists $row_votehead_vals{$vthead} ) {
						$tbody .= "<TD>" . format_currency($row_votehead_vals{$vthead});
					}
					else {
						$tbody .= "<TD>&nbsp;";
					}
				}
			}

			#append credits
			if ($dr_cr == 1 or $dr_cr == 3) {

				if ($dr_cr == 1) {
					$tbody .= "<TD>$to_from_bank";	
				}
				$tbody .= $blank_entries;
		
			}

			$tbody .= "<TD>$to_from_bank";
=cut
			
			#Debits or Bank Actions
			if ($dr_cr == 1 or $dr_cr == 3) {
				for my $vthead (sort {$ordered_voteheads{$a} <=> $ordered_voteheads{$b} } keys %ordered_voteheads) {
				
					if ( exists $row_votehead_vals{$vthead} ) {
						$dr_table .= "<TD>" . format_currency($row_votehead_vals{$vthead});
					}
					else {
						$dr_table .= "<TD>&nbsp;";
					}
				}
				
			}
			#Prepayments, Credits or Bank Actions
			if ($dr_cr == 1.25 or $dr_cr == 2 or $dr_cr == 3) {
				for my $vthead (sort {$ordered_voteheads{$a} <=> $ordered_voteheads{$b} } keys %ordered_voteheads) {
				
					if ( exists $row_votehead_vals{$vthead} ) {
						$cr_table .= "<TD>" . format_currency($row_votehead_vals{$vthead});
					}
					else {
						$cr_table .= "<TD>&nbsp;";
					}
				}
				
			}

		}

		#votehead totals
		#$tbody .= qq!<TR style="font-weight: bold; font-size: 1.2em"><TD colspan="2" style="text-align: center">Total!;

		$dr_table .= qq!<TR style="font-weight: bold; font-size: 1.2em"><TD colspan="6" style="text-align: center">Total!;
		$cr_table .= qq!<TR style="font-weight: bold; font-size: 1.2em"><TD colspan="7" style="text-align: center">Total!;	

		#debits total	
		for my $vthead (sort {$ordered_voteheads{$a} <=> $ordered_voteheads{$b} } keys %ordered_voteheads) {
			if ( exists $votehead_totals{"dr_" . $vthead} ) {
				$dr_table .= "<TD>". format_currency($votehead_totals{"dr_" . $vthead});
				#$tbody .= "<TD>". format_currency($votehead_totals{$dr_or_cr . $vthead});	
			}
			else {
				$dr_table .= "<TD>&nbsp;";
				#$tbody .= "<TD>&nbsp;";
			}
		}

		#credits total
		for my $vthead (sort {$ordered_voteheads{$a} <=> $ordered_voteheads{$b} } keys %ordered_voteheads) {
			if ( exists $votehead_totals{"cr_" . $vthead} ) {
				$cr_table .= "<TD>". format_currency($votehead_totals{"cr_" . $vthead});
				#$tbody .= "<TD>". format_currency($votehead_totals{$dr_or_cr . $vthead});	
			}
			else {
				$cr_table .= "<TD>&nbsp;";
				#$tbody .= "<TD>&nbsp;";
			}
		}

		#$tbody .= "<TD>&nbsp;";

		#$tbody .= "</tbody>";

		$dr_table .= "</tbody></table>";
		$cr_table .= "</tbody></table>";

		my $opening_balances_table = "";

		#write opening balances
		if ( scalar(keys %opening_balances) > 0 ) {

			$opening_balances_table .= qq!<h4>Opening Balances</h4><TABLE border="1" cellpadding="5%" cellspacing="5%"><THEAD><TH>Bank Account<TH>Balance</THEAD><TBODY>!;
			for my $accnt (keys %opening_balances) {
				my $formatted_amnt = format_currency($opening_balances{$accnt});
				$opening_balances_table .= qq!<TR><TD style="font-weight: bold">$accnt<TD>$formatted_amnt!;
			}
			$opening_balances_table .= "</TABLE>";
		}

		my $closing_balances_table = "";

		#write closing balances
		if ( scalar(keys %closing_balances) > 0 ) {

			$closing_balances_table .= qq!<h4>Closing Balances</h4><TABLE border="1" cellpadding="5%" cellspacing="5%"><THEAD><TH>Bank Account<TH>Balance</THEAD><TBODY>!;
			for my $accnt (keys %closing_balances) {
				my $formatted_amnt = format_currency($closing_balances{$accnt});
				$closing_balances_table .= qq!<TR><TD style="font-weight: bold">$accnt<TD>$formatted_amnt!;
			}
			$closing_balances_table .= "</TABLE>";
		}

		$content =
qq*
<!DOCTYPE html>
<html lang="en">

<head>
<title>Spanj::Accounts Management Information System::View Cashbook</title>

<STYLE type="text/css">

\@media print {
	body {
		margin-top: 0px;
		margin-bottom: 0px;
		padding: 0px;
		font-size: 11pt;
		font-family: "Times New Roman", serif;	
	}

	div.no_header {
		display: none;
	}
}

\@media screen {
	div.noheader {}	
}

th.rotate {
	height: 300px;
	white-space: nowrap;
}

th.rotate > div {
	transform:
		rotate(270deg)
		translate(-140px,0px);
	width: 30px;
}

th.rotate > div > span {
	border-bottom: 1px solid #ccc;	
}

</STYLE>
</head>

<body>

<div class="no_header">
$header
</div>
$opening_balances_table
<p>
$dr_table
<p>
$cr_table
$closing_balances_table
</body>

</html>
*;
		#log view
		my @today = localtime;	
		my $day_month_yr = sprintf "%d-%02d-%02d", $today[5] + 1900, $today[4] + 1, $today[3];

		open (my $log_f, ">>$log_d/user_actions-$day_month_yr.log");
      		if ($log_f) {

			my $time = sprintf "%d-%02d-%02d-%02d%02d.%02d", $today[5]+1900,$today[4]+1,$today[3],$today[2],$today[1],$today[0];
			flock ($log_f, LOCK_EX) or print STDERR "Could not log view cashbook for $id due to flock error: $!$/";
			seek ($log_f, 0, SEEK_END);	
 
			print $log_f "$id VIEW CASHBOOK $time\n";
			flock ($log_f, LOCK_UN);
       			close $log_f;
  	    	 }
		else {
			print STDERR "Could not log view cashbook $id: $!\n";
		}	
	}

}
}

if ( not $post_mode ) {

	my @month_days = (31,28,31,30,31,30,31,31,30,31,30,31);

	my @today = localtime;

	my $mday = $today[3];
	my $month = $today[4] + 1;
	my $yr = $today[5] + 1900;

	my $today = sprintf("%02d/%02d/%d", $mday, $month, $yr);

	my $wkday = $today[6];

	$mday -= $wkday;

	if ($mday < 1) {

		my $sup = $mday;

		#if I was in January, jump to December 
		#of the previous year
		if ( $month == 1 ) {
			$yr--;
			$month = 12;
			$mday = 31 + $sup;	
		}
		else {
			#leap year
			if ( $yr % 4 == 0 ) {
				$month_days[1] = 29;
			}
		
			$mday = $month_days[$month - 2] + $sup;
			$month--;
		}
	}

	my $week_start = sprintf("%02d/%02d/%d", $mday, $month, $yr);
	my $month_start = sprintf("01/%02d/%d", $month, $yr);
	my $fy_start = sprintf("01/01/%d", $yr);

	my $conf_code = gen_token();
	$session{"confirm_code"} = $conf_code;

	$content =
qq*

<!DOCTYPE html>
<html lang="en">

<head>
<title>Spanj::Accounts Management Information System::View Cashbook</title>

<SCRIPT>

var today = '$today';
var week_start = '$week_start';
var month_start = '$month_start';
var fy_start = '$fy_start';

var date_re = /^([0-9][0-9]?)\*\\/\*([0-9][0-9]?)\*\\/\*(?:[0-9][0-9](?:[0-9][0-9])?)\*\$/;

function check_date(elem) {

	var date = document.getElementById(elem).value;
	var date_bts = date.match(date_re);

	if (date_bts) {
		var day = date_bts[1];
		if (day < 32) {
			var month = date_bts[2];
			if (month < 13) {	
				document.getElementById(elem + "_err").innerHTML = "";
			}
			else {
				document.getElementById(elem + "_err").innerHTML = "\*";
			}
		}
		else {
			document.getElementById(elem + "_err").innerHTML = "\*";
		}
	}
	else {
		document.getElementById(elem + "_err").innerHTML = "\*";
	}

}

function change_date() {
	var selected_opt = document.getElementById("date_select").value;

	switch(selected_opt) {

		case "today":

			document.getElementById("start_date").value = today;
			document.getElementById("stop_date").value = today;

			document.getElementById("start_date").disabled = true;
			document.getElementById("stop_date").disabled = true;
			break;

		case "this_week":
			document.getElementById("start_date").value = week_start;
			document.getElementById("stop_date").value = today;

			document.getElementById("start_date").disabled = true;
			document.getElementById("stop_date").disabled = true;
			break;

		case "this_month":
			document.getElementById("start_date").value = month_start;
			document.getElementById("stop_date").value = today;

			document.getElementById("start_date").disabled = true;
			document.getElementById("stop_date").disabled = true;
			break;

		case "this_fy":
			document.getElementById("start_date").value = fy_start;
			document.getElementById("stop_date").value = today;

			document.getElementById("start_date").disabled = true;
			document.getElementById("stop_date").disabled = true;
			break;

		case "specific_dates":
			document.getElementById("start_date").disabled = false;
			document.getElementById("stop_date").disabled = false;

	}
}

</SCRIPT>

</head>
<body>
$header
$feedback
<FORM method="POST" action="/cgi-bin/cashbook.cgi">

<input type="hidden" name="confirm_code" value="$conf_code">

<TABLE cellspacing="5%" cellpadding="5%" style="text-align: left">
<TR><TH>Duration<TD>

<SELECT id="date_select" name="date_select" onchange="change_date()">

<OPTION value="today" title="Today">Today</OPTION>
<OPTION selected value="this_week" title="This Week">This Week</OPTION>
<OPTION value="this_month" title="This Month">This Month</OPTION>
<OPTION value="this_fy" title="Entire FY">Entire FY</OPTION>
<OPTION value="specific_dates" title="Specific Duration">Specific Duration</OPTION>

</SELECT>

</TABLE>
<TABLE>
<TR><TH><LABEL for="start_date">Start Date</LABEL>&nbsp;<span style="color: red" id="start_date_err"></span><INPUT disabled="1" name="start_date" id="start_date" type="text" size="10" maxlength="10" value="$week_start" onkeyup="check_date('start_date')"><TH><LABEL for="stop_date">Stop Date</LABEL>&nbsp;<span style="color: red" id="stop_date_err"></span><INPUT disabled="1" name="stop_date" id="stop_date" type="text" size="10" maxlength="10" value="$today" onkeyup="check_date('stop_date')">
</TABLE>
<p><LABEL style="font-weight: bold">Show votehead sub-categories</LABEL><INPUT type="checkbox" name="show_sub_categories" checked value="1">
<p><INPUT type="submit" name="view_print" value="View/Print">&nbsp;&nbsp;<INPUT type="submit" name="download" value="Download">
</FORM>
</body>
</html>

*;

}

print "Status: 200 OK\r\n";
print "Content-Type: text/html; charset=UTF-8\r\n";

my $len = length($content);
print "Content-Length: $len\r\n";

my @new_sess_array = ();

for my $sess_key (keys %session) {
	push @new_sess_array, $sess_key."=".$session{$sess_key};        
}
my $new_sess = join ('&',@new_sess_array);

print "X-Update-Session: $new_sess\r\n";

print "\r\n";
print $content;
$con->disconnect() if (defined $con and $con);

sub gen_token {
	my @key_space = ("A","B","C","D","E","F","0","1","2","3","4","5","6","7","8","9");
	my $len = 5 + int(rand 15);
	if (@_ and ($_[0] eq "1")) {
		@key_space = ("A","B","C","D","E","F","G","H","J","K","L","M","N","P","T","W","X","Z","7","0","1","2","3","4","5","6","7","8","9");
		$len = 10 + int (rand 5);
	}
	my $token = "";
	for (my $i = 0; $i < $len; $i++) {
		$token .= $key_space[int(rand @key_space)];
	}
	return $token;
}

sub htmlspecialchars {
	my $cp = $_[0];
	$cp =~ s/&/&#38;/g;
        $cp =~ s/</&#60;/g;
        $cp =~ s/>/&#62;/g;
        $cp =~ s/'/&#39;/g;
        $cp =~ s/"/&#34;/g;
        return $cp;
}

sub remove_padding {

	return undef unless (@_);

	my $packed = $_[0];
	my @bytes = unpack("C*", $packed);
	
	my $final_index = $#bytes;
	my $pad_size = $bytes[$final_index];

	my $msg_valid = 1;
	#verify msg
	
	for ( my $i = 1; $i < $pad_size; $i++ ) {
		unless ( $bytes[$final_index - $i] == $pad_size ) {
			$msg_valid = 0;
			last;
		}
	}

	if ($msg_valid) {
		my $msg_size = ($final_index + 1) - $pad_size;
		my $msg = unpack("A${msg_size}", $packed);

		return $msg;
	}
	return undef;
}

sub add_padding {

	return undef unless (@_);

	my $tst_str = $_[0];
	my $tst_str_len = length($tst_str);

	my $rem = 16 - ($tst_str_len % 16);
	if ($rem == 0 ) {
		$rem = 16;
	}

	my @extras = ();
	for (my $i = 0; $i < $rem; $i++) {
		push @extras, $rem;
	}

	my $padded = pack("A${tst_str_len}C${rem}", $tst_str, @extras);
	return $padded;
}

sub format_currency {

	return "" unless (@_);

	my $formatted_num = $_[0];

	if ( $_[0] =~ /^(\-?)(\d+)(\.(?:\d))?$/ ) {

		my $sign = $1;
		my $shs = $2;
		my $cents = $3;

		$sign = "" if (not defined $sign);
		$cents = "" if (not defined $cents);

		my $num_blocks = int(length($shs) / 3);

		if ($num_blocks > 0) {

			my @nums = ();

			my $surplus = length($shs) % 3;
			if ($surplus > 0) {
				push @nums, substr($shs, 0, $surplus);
			}

			for (my $i = 0; $i < $num_blocks; $i++) {
				push @nums, substr($shs, $surplus + ($i * 3),3);
			}

			$formatted_num = join(",", @nums); 
		}

		$formatted_num = $sign . $formatted_num;
		$formatted_num .= $cents;
	}
	return $formatted_num;
}
